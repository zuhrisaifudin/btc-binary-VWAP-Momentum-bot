import time
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

from src.market_regime_analyzer import MarketRegimeAnalyzer, MarketRegimeInfo
from src.smart_scaling_engine import SmartScalingEngine, ScalingConfig, ScalingResult
from src.order_executor import OrderExecutor

logger = logging.getLogger("btc_live.dual_side_manager")

@dataclass
class DualSideConfig:
    """Configuration for Dual-Side Scaling Strategy"""
    scaling_parts: int = 10
    scaling_duration_sec: float = 120.0
    use_conservative_kelly: bool = True
    dominant_allocation_pct: float = 0.75
    insurance_allocation_pct: float = 0.25
    max_daily_trades: int = 20
    daily_stop_loss_usd: float = -5.0
    max_consecutive_losses: int = 3
    circuit_breaker_duration_min: int = 15
    total_capital: float = 100.0  # Used as bankroll for Kelly Criterion

@dataclass
class TradeDecision:
    """Trading decision output"""
    should_trade: bool
    kelly_fraction: float
    total_budget: float
    dominant_budget: float
    dominant_side: str
    insurance_budget: float
    insurance_side: str
    confidence: float
    regime_info: MarketRegimeInfo

class DualSideScalingManager:
    """
    Manages the overall Dual-Side Scaling and Regime Adaptation strategy.
    """
    def __init__(self, order_executor: OrderExecutor, config: Optional[DualSideConfig] = None):
        self.executor = order_executor
        self.config = config or DualSideConfig()
        
        # Initialize sub-components
        self.regime_analyzer = MarketRegimeAnalyzer(
            min_price_threshold=0.30,
            max_price_threshold=0.70
        )
        
        scaling_conf = ScalingConfig(
            parts=self.config.scaling_parts,
            total_duration_sec=self.config.scaling_duration_sec
        )
        self.scaling_engine = SmartScalingEngine(order_executor, scaling_conf)
        
        # Statistics and risk management state
        self.daily_trades = 0
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.regime_count: Dict[str, int] = {}
        self.circuit_breaker_until: float = 0.0
        self.last_reset_day = time.gmtime().tm_yday

    def _check_and_reset_daily(self) -> None:
        """Reset stats if a new day (UTC) has started"""
        current_day = time.gmtime().tm_yday
        if current_day != self.last_reset_day:
            logger.info("New day detected. Resetting daily trading statistics.")
            self.daily_trades = 0
            self.daily_pnl = 0.0
            self.last_reset_day = current_day

    def update_price_data(self, price: float) -> None:
        """Forward price update to the analyzer"""
        self.regime_analyzer.update_price(price)

    def update_order_book_data(self, bids: List[Dict[str, Any]], asks: List[Dict[str, Any]]) -> None:
        """Forward order book update to the analyzer"""
        self.regime_analyzer.update_order_book(bids, asks)

    def analyze_regime(self) -> MarketRegimeInfo:
        """Perform regime analysis"""
        return self.regime_analyzer.analyze_regime()

    def should_trade_regime(self, token_price: float) -> bool:
        """Check if regime rules permit trading"""
        should_tr, _ = self.regime_analyzer.should_trade(token_price)
        return should_tr

    def calculate_trade_decision(self, win_prob: float, token_price: float) -> Optional[TradeDecision]:
        """
        Calculate sizing and budgeting based on Kelly Criterion and market regime.
        """
        self._check_and_reset_daily()
        
        # Check circuit breaker
        if time.time() < self.circuit_breaker_until:
            logger.warning("Trading blocked by Circuit Breaker")
            return None
            
        # Check daily limits
        if self.daily_trades >= self.config.max_daily_trades:
            logger.warning(f"Daily trade limit reached: {self.daily_trades}/{self.config.max_daily_trades}")
            return None
            
        if self.daily_pnl <= self.config.daily_stop_loss_usd:
            logger.warning(f"Daily stop loss hit: P&L ${self.daily_pnl:.2f} <= Stop loss ${self.config.daily_stop_loss_usd:.2f}")
            return None

        # Analyze current regime
        regime_info = self.regime_analyzer.regime_info
        should_tr, dominant_side = self.regime_analyzer.should_trade(token_price)
        
        if not should_tr or not dominant_side:
            return None

        # Calculate Kelly fraction
        kelly_frac, _ = self.regime_analyzer.get_kelly_allocation(
            win_prob, token_price, self.config.use_conservative_kelly
        )
        
        if kelly_frac <= 0:
            return None

        # Calculate budget allocation
        bankroll = getattr(self.executor, 'initial_balance', self.config.total_capital)
        total_budget = kelly_frac * bankroll
        
        # Impose a small minimum budget constraint
        if total_budget < 0.10:
            return None

        dominant_budget = total_budget * self.config.dominant_allocation_pct
        insurance_budget = total_budget * self.config.insurance_allocation_pct
        
        insurance_side = "DOWN" if dominant_side == "UP" else "UP"
        
        summary = self.regime_analyzer.get_regime_summary()
        confidence = summary.get("confidence", 0.5)

        return TradeDecision(
            should_trade=True,
            kelly_fraction=kelly_frac,
            total_budget=total_budget,
            dominant_budget=dominant_budget,
            dominant_side=dominant_side,
            insurance_budget=insurance_budget,
            insurance_side=insurance_side,
            confidence=confidence,
            regime_info=regime_info
        )

    async def execute_dual_side_trade(
        self,
        up_token_id: str,
        down_token_id: str,
        win_prob: float
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Executes both Dominant and Insurance sides of the trade.
        """
        # Determine token price based on order book
        dominant_side = self.regime_analyzer.regime_info.dominant_side
        if not dominant_side:
            logger.warning("No dominant side detected, skipping trade execution.")
            return False, {}

        dominant_token_id = up_token_id if dominant_side == "UP" else down_token_id
        book_data = await self.executor.get_order_book(dominant_token_id)
        if not book_data:
            logger.warning(f"Could not get order book for {dominant_token_id}")
            return False, {}

        best_ask = book_data.get("best_ask", 0.50)
        
        decision = self.calculate_trade_decision(win_prob, best_ask)
        if not decision or not decision.should_trade:
            logger.info("Decision engine rejected trade.")
            return False, {}

        logger.info(f"Executing Dual-Side Trade: Dominant={decision.dominant_side} (${decision.dominant_budget:.2f}), Insurance={decision.insurance_side} (${decision.insurance_budget:.2f})")

        # Select actual tokens
        dominant_token = up_token_id if decision.dominant_side == "UP" else down_token_id
        insurance_token = down_token_id if decision.dominant_side == "UP" else up_token_id

        # 1. Execute dominant position
        dominant_res = await self.scaling_engine.scale_in(
            token_id=dominant_token,
            total_budget=decision.dominant_budget,
            side="BUY"
        )

        # 2. Execute insurance position
        insurance_res = await self.scaling_engine.scale_in(
            token_id=insurance_token,
            total_budget=decision.insurance_budget,
            side="BUY"
        )

        result = {
            "dominant_success": dominant_res.success,
            "insurance_success": insurance_res.success,
            "dominant_filled": dominant_res.contracts_filled,
            "insurance_filled": insurance_res.contracts_filled,
            "dominant_price": dominant_res.avg_price,
            "insurance_price": insurance_res.avg_price,
            "dominant_cost": dominant_res.total_cost,
            "insurance_cost": insurance_res.total_cost
        }
        
        success = dominant_res.success or insurance_res.success
        return success, result

    def record_trade_outcome(self, won: bool, pnl: float, regime: str, confidence: float) -> None:
        """
        Record the results of a resolved trade, updating stats and risk bounds.
        """
        self._check_and_reset_daily()
        
        self.daily_trades += 1
        self.daily_pnl += pnl
        
        # Track regime occurrence
        self.regime_count[regime] = self.regime_count.get(regime, 0) + 1
        
        # Check consecutive losses and circuit breaker
        if won:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.config.max_consecutive_losses:
                breaker_duration = self.config.circuit_breaker_duration_min * 60
                self.circuit_breaker_until = time.time() + breaker_duration
                logger.warning(f"Circuit breaker triggered due to {self.consecutive_losses} consecutive losses! Trading blocked for {self.config.circuit_breaker_duration_min} minutes.")

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics for dashboard and logging"""
        self._check_and_reset_daily()
        return {
            "daily_trades": self.daily_trades,
            "daily_pnl": self.daily_pnl,
            "consecutive_losses": self.consecutive_losses,
            "regime_count": self.regime_count,
            "circuit_breaker_active": time.time() < self.circuit_breaker_until,
            "circuit_breaker_remaining_sec": max(0.0, self.circuit_breaker_until - time.time())
        }
