import time
import numpy as np
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass

from src.regime_strategy import (
    HurstExponentCalculator,
    OrderFlowImbalanceCalculator,
    KellyCriterionCalculator,
    RegimeDetector
)

@dataclass
class MarketRegimeInfo:
    """Information about the current market regime"""
    regime: str
    dominant_side: Optional[str]
    hurst: float
    ofi: float
    ofi_ma: float
    recent_move_pct: float
    timestamp: float

class MarketRegimeAnalyzer:
    """
    Analyzes market regime using Hurst Exponent and Order Flow Imbalance.
    """
    def __init__(
        self,
        price_window: int = 20,
        ofi_window: int = 5,
        min_price_threshold: float = 0.30,
        max_price_threshold: float = 0.70
    ):
        self.price_window = price_window
        self.ofi_window = ofi_window
        self.min_price_threshold = min_price_threshold
        self.max_price_threshold = max_price_threshold
        
        self.price_history: List[float] = []
        self.bids: List[Dict[str, Any]] = []
        self.asks: List[Dict[str, Any]] = []
        self.ofi_history: List[float] = []
        self.ofi_calculator = OrderFlowImbalanceCalculator()
        
        self.regime_info = MarketRegimeInfo(
            regime="NEUTRAL",
            dominant_side=None,
            hurst=0.5,
            ofi=0.0,
            ofi_ma=0.0,
            recent_move_pct=0.0,
            timestamp=time.time()
        )

    def update_price(self, price: float) -> None:
        """Update price history"""
        self.price_history.append(price)
        if len(self.price_history) > self.price_window:
            self.price_history.pop(0)

    def update_order_book(self, bids: List[Dict[str, Any]], asks: List[Dict[str, Any]]) -> None:
        """Update order book data"""
        self.bids = bids
        self.asks = asks

    def get_recent_move_pct(self) -> float:
        """Calculate recent price move percentage"""
        if len(self.price_history) < 2:
            return 0.0
        return ((self.price_history[-1] - self.price_history[0]) / self.price_history[0]) * 100.0

    def analyze_regime(self, recent_move_pct: Optional[float] = None) -> MarketRegimeInfo:
        """
        Analyze current market regime and determine dominant trading side
        """
        if len(self.price_history) < 2:
            self.regime_info = MarketRegimeInfo(
                regime="NEUTRAL",
                dominant_side=None,
                hurst=0.5,
                ofi=0.0,
                ofi_ma=0.0,
                recent_move_pct=0.0,
                timestamp=time.time()
            )
            return self.regime_info

        # Calculate Hurst exponent
        hurst = HurstExponentCalculator.calculate(self.price_history)

        # Calculate OFI
        ofi = 0.0
        if self.bids and self.asks:
            ofi = self.ofi_calculator.update_multi_level(self.bids, self.asks)
            self.ofi_history.append(ofi)
            if len(self.ofi_history) > self.ofi_window:
                self.ofi_history.pop(0)

        ofi_ma = float(np.mean(self.ofi_history)) if self.ofi_history else 0.0

        if recent_move_pct is None:
            recent_move_pct = self.get_recent_move_pct()

        regime, dominant_side = RegimeDetector.detect_with_direction(
            hurst, ofi_ma, recent_move_pct
        )

        self.regime_info = MarketRegimeInfo(
            regime=regime,
            dominant_side=dominant_side,
            hurst=hurst,
            ofi=ofi,
            ofi_ma=ofi_ma,
            recent_move_pct=recent_move_pct,
            timestamp=time.time()
        )
        return self.regime_info

    def get_kelly_allocation(
        self,
        win_prob: float,
        token_price: float,
        use_conservative: bool = False
    ) -> Tuple[float, Optional[str]]:
        """
        Calculate Kelly Criterion allocation percentage
        """
        side = self.regime_info.dominant_side
        if use_conservative:
            kelly_frac = KellyCriterionCalculator.calculate_conservative(win_prob, token_price)
        else:
            kelly_frac = KellyCriterionCalculator.calculate(win_prob, token_price)
        return kelly_frac, side

    def should_trade(self, token_price: float) -> Tuple[bool, Optional[str]]:
        """
        Determine if the bot should trade based on regime and price parameters
        """
        if self.regime_info.regime == "NEUTRAL":
            return False, None

        if token_price < self.min_price_threshold or token_price > self.max_price_threshold:
            return False, None

        return True, self.regime_info.dominant_side

    def get_regime_summary(self) -> Dict[str, Any]:
        """
        Get summary dictionary of the regime analysis
        """
        last_price = self.price_history[-1] if self.price_history else 0.50
        should_tr, side = self.should_trade(last_price)
        confidence = RegimeDetector.calculate_confidence(
            self.regime_info.hurst, self.regime_info.ofi_ma
        )

        return {
            "regime": self.regime_info.regime,
            "dominant_side": self.regime_info.dominant_side,
            "hurst": self.regime_info.hurst,
            "ofi": self.regime_info.ofi,
            "ofi_ma": self.regime_info.ofi_ma,
            "recent_move_pct": self.regime_info.recent_move_pct,
            "should_trade": should_tr,
            "recommendation": self.regime_info.dominant_side,
            "confidence": confidence
        }
