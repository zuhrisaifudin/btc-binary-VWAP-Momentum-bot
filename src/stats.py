#!/usr/bin/env python3
"""
Trading statistics module.

Contains TradingStats, Position, TradeRecord classes for position and trade tracking.
"""

import time
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple


@dataclass
class Position:
    """Current open position"""
    token_name: str
    token_id: str
    opposite_token_id: str
    entry_price: float
    contracts: int
    entry_time: float
    market_slug: str
    hedged: bool = False
    hedge_contracts: int = 0
    hedge_price: float = 0.0
    min_price_seen: float = 0.0  # Lowest price after entry (for drawdown tracking)
    awaiting_resolution: bool = False  # True if market ended but outcome not yet determined


@dataclass
class TradeRecord:
    """Completed trade record"""
    market_slug: str
    token_name: str
    entry_price: float
    exit_price: float
    contracts: int
    pnl: float
    won: bool
    timestamp: float
    max_drawdown_abs: float = 0.0   # Max absolute price drop from entry
    max_drawdown_pct: float = 0.0   # Max percentage drawdown from entry
    hedged: bool = False
    hedge_contracts: int = 0
    hedge_price: float = 0.0
    # How the win/loss outcome was determined
    # "chainlink_oracle"  - from BTC anchor/current price (same oracle Polymarket uses)
    # "gamma_outcome"     - from Gamma API market.closed + outcomePrices (official resolution)
    # "preliminary_last_price" - legacy: guessed from token last_price >= 0.70 (inaccurate, kept only for old logs)
    resolution_source: str = "preliminary_last_price"
    outcome: Optional[str] = None  # Which side won: "UP" or "DOWN"


@dataclass
class MarketState:
    """Current market state"""
    slug: str = ""
    end_time: float = 0.0
    duration_sec: float = 300.0
    btc_price: float = 0.0


class TradingStats:
    """Trading statistics and position tracking."""

    def __init__(self, log_file: str = "logs/trading_log.json"):
        self.log_file = log_file
        self.markets_seen: int = 0
        self.current_market_slug: str = ""
        self.position_closed_this_market: bool = False
        self.entry_blocked: bool = False

        # Daily tracking for risk management
        self.daily_trades: int = 0
        self.daily_pnl: float = 0.0
        self.last_trade_date: str = ""
        self.max_daily_trades: int = 20  # Will be set from config
        self.daily_stop_loss: float = -5.0  # Default overridden from config in initialize()

        # FASE 1: positions whose market ended but outcome could not be determined
        # from Chainlink (e.g. RTDS disconnected). Resolved later by the Gamma
        # resolution poller reading market.closed + outcomePrices.
        self.pending_resolutions: List[dict] = []

        self._load()
        self._check_new_day()

    def _load(self):
        """Load trading history from JSON file."""
        try:
            with open(self.log_file, 'r') as f:
                data = json.load(f)
                # Load trades if present
                if 'trades' in data:
                    self.trades = [TradeRecord(**t) for t in data['trades']]
                else:
                    self.trades = []
                # Load other stats
                self.daily_pnl = data.get('daily_pnl', 0.0)
                self.daily_trades = data.get('daily_trades', 0)
                self.last_trade_date = data.get('last_trade_date', "")
                self.max_daily_trades = data.get('max_daily_trades', 20)
                self.daily_stop_loss = data.get('daily_stop_loss', -5.0)
        except Exception:
            # Initialize empty if file doesn't exist/corrupt
            self.trades = []

    def _save(self):
        """Save trading history to JSON file."""
        try:
            data = {
                'trades': [t.__dict__ for t in self.trades],
                'daily_pnl': self.daily_pnl,
                'daily_trades': self.daily_trades,
                'last_trade_date': self.last_trade_date,
                'max_daily_trades': self.max_daily_trades,
                'daily_stop_loss': self.daily_stop_loss
            }
            with open(self.log_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving trading log: {e}")

    def _check_new_day(self):
        """Check if a new day started and reset daily stats if needed."""
        current_date = time.strftime("%Y-%m-%d", time.localtime())
        if self.last_trade_date != current_date:
            # Reset daily stats for new day
            self.daily_pnl = 0.0
            self.daily_trades = 0
            self.last_trade_date = current_date
            self._save()

    def can_enter(self) -> bool:
        """Check if we can enter a new position."""
        if self.position is None and not self.position_closed_this_market and not self.entry_blocked:
            if self.daily_trades >= self.max_daily_trades:
                return False

            if self.daily_pnl <= self.daily_stop_loss:
                return False

            return True
        return False

    def block_entry(self, reason: str = ""):
        """Block entry to prevent repeated attempts after timeout."""
        self.entry_blocked = True
        logger.info(f"Entry blocked: {reason}")

    def record_entry(self, token_name: str, token_id: str, opposite_token_id: str,
                     price: float, contracts: int, market_slug: str):
        """Record a new position entry."""
        self.position = Position(
            token_name=token_name,
            token_id=token_id,
            opposite_token_id=opposite_token_id,
            entry_price=price,
            contracts=contracts,
            entry_time=time.time(),
            market_slug=market_slug,
            min_price_seen=price  # Start tracking from entry price
        )

    def record_hedge(self, contracts: int, price: float):
        """Record hedge position opening."""
        if self.position:
            self.position.hedged = True
            self.position.hedge_contracts = contracts
            self.position.hedge_price = price

    def update_drawdown(self, current_price: float):
        """Track minimum price seen since entry for drawdown calculation."""
        if self.position and current_price > 0:
            if current_price < self.position.min_price_seen:
                self.position.min_price_seen = current_price

    def _build_trade_record(
        self,
        pos: Position,
        won: bool,
        resolution_source: str,
        btc_anchor: float,
        btc_current: float,
    ) -> Tuple[TradeRecord, float]:
        """Compute a TradeRecord + PnL from a position and a resolved outcome."""
        entry_cost = pos.contracts * pos.entry_price

        # PnL with hedge consideration (hedge wins when main loses)
        hedge_cost = 0.0
        hedge_payout = 0.0
        if pos.hedged:
            hedge_cost = pos.hedge_contracts * pos.hedge_price
            if not won:
                hedge_payout = pos.hedge_contracts * 1.00

        if won:
            pnl = (pos.contracts - entry_cost) - hedge_cost
        else:
            pnl = (-entry_cost - hedge_cost) + hedge_payout

        final_price = 1.0 if won else 0.0  # actual per-contract payout
        dd_abs = max(0.0, pos.entry_price - pos.min_price_seen)
        dd_pct = (dd_abs / pos.entry_price * 100) if pos.entry_price > 0 else 0.0
        outcome_name = pos.token_name if won else (
            "DOWN" if pos.token_name == "UP" else "UP"
        )

        record = TradeRecord(
            market_slug=pos.market_slug,
            token_name=pos.token_name,
            entry_price=pos.entry_price,
            exit_price=final_price,
            contracts=pos.contracts,
            pnl=pnl,
            won=won,
            timestamp=time.time(),
            max_drawdown_abs=dd_abs,
            max_drawdown_pct=dd_pct,
            hedged=pos.hedged,
            hedge_contracts=pos.hedge_contracts,
            hedge_price=pos.hedge_price,
            resolution_source=resolution_source,
            outcome=outcome_name
        )

        return record, pnl

    def close_position(self, won_or_final_price=None, resolution_source: str = "chainlink_oracle",
                      btc_anchor: float = 0.0, btc_current: float = 0.0, won: Optional[bool] = None) -> Optional[TradeRecord]:
        """Close the current position using the resolved market outcome.

        Backward compatibility: accepts either won: bool (new) or final_price: float (old).
        """
        if not self.position:
            return None

        # Handle backward compatibility
        if won is not None:
            won_val = won
            final_price = 1.0 if won_val else 0.0
        elif isinstance(won_or_final_price, bool):
            won_val = won_or_final_price
            final_price = 1.0 if won_val else 0.0
        else:
            # Legacy mode
            final_price = won_or_final_price
            won_val = final_price >= 0.70 if final_price is not None else False
            resolution_source = "preliminary_last_price"

        record, pnl = self._build_trade_record(
            self.position, won_val, resolution_source, btc_anchor, btc_current
        )

        self.daily_pnl += pnl
        self.daily_trades += 1
        self.trades.append(record)
        self.position = None
        self.position_closed_this_market = True
        self._save()

        return record

    def add_pending_resolution(self, position: Position, outcome_prices: List[float]):
        """Add a position awaiting resolution."""
        self.pending_resolutions.append({
            'position': position,
            'outcome_prices': outcome_prices,
            'timestamp': time.time()
        })

    def resolve_pending(self, won: bool, resolution_source: str):
        """Resolve the oldest pending position."""
        if not self.pending_resolutions:
            return None

        pending = self.pending_resolutions.pop(0)
        record, pnl = self._build_trade_record(
            pending['position'], won, resolution_source, 0.0, 0.0
        )

        self.daily_pnl += pnl
        self.daily_trades += 1
        self.trades.append(record)
        self._save()

        return record

    def total_pnl(self) -> float:
        """Calculate total P&L across all trades."""
        return sum(t.pnl for t in self.trades)

    def win_count(self) -> int:
        """Count winning trades."""
        return sum(1 for t in self.trades if t.won)

    def trade_count(self) -> int:
        """Get total trade count."""
        return len(self.trades)