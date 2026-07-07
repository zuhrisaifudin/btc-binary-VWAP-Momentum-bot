"""
Deferred Resolution Manager for Polymarket BTC Binary Bot
Handles markets that end before resolution is available
"""

import asyncio
import logging
import time
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
from collections import deque
import json

logger = logging.getLogger("btc_live.deferred_resolution")

@dataclass
class PendingResolution:
    """Information about a pending resolution"""
    market_slug: str
    condition_id: str
    end_time: float
    position_data: Dict[str, Any]
    created_at: float
    resolved_at: Optional[float] = None
    resolution_result: Optional[Dict[str, Any]] = None

@dataclass
class ResolutionResult:
    """Result of resolution"""
    market_slug: str
    condition_id: str
    won: bool
    outcome: str
    resolution_price: float
    timestamp: float
    source: str  # "gamma_api", "chainlink", "last_price"

class DeferredResolutionManager:
    """
    Manages deferred resolution of binary markets
    """

    def __init__(
        self,
        max_pending: int = 10,
        resolution_interval_sec: int = 30,
        max_wait_minutes: int = 120
    ):
        self.pending_resolutions: deque[PendingResolution] = deque(maxlen=max_pending)
        self.resolution_interval = resolution_interval_sec
        self.max_wait_minutes = max_wait_minutes
        self.markets_seen: set[str] = set()
        self.trade_number = 0

    def add_pending_resolution(
        self,
        market_slug: str,
        condition_id: str,
        end_time: float,
        position_data: Dict[str, Any]
    ) -> None:
        """
        Add a market to pending resolution list

        Args:
            market_slug: Market identifier
            condition_id: Condition ID
            end_time: When the market ends
            position_data: Position data snapshot
        """
        # Check if we've already seen this market
        if market_slug in self.markets_seen:
            logger.warning(f"Market {market_slug} already in pending list")
            return

        # Create pending resolution
        pending = PendingResolution(
            market_slug=market_slug,
            condition_id=condition_id,
            end_time=end_time,
            position_data=position_data,
            created_at=time.time()
        )

        self.pending_resolutions.append(pending)
        self.markets_seen.add(market_slug)

        logger.info(
            f"Added to pending resolution: {market_slug} "
            f"(end time: {time.ctime(end_time)})"
        )

    async def resolve_pending_markets(self, gamma_api_client) -> List[ResolutionResult]:
        """
        Poll and resolve pending markets

        Args:
            gamma_api_client: API client for Gamma API

        Returns:
            List of resolved results
        """
        results = []
        current_time = time.time()

        # Check each pending resolution
        for i, pending in enumerate(list(self.pending_resolutions)):
            # Skip if too early
            if current_time < pending.end_time:
                continue

            # Skip if already resolved
            if pending.resolved_at is not None:
                continue

            # Check if exceeded max wait time
            if current_time - pending.created_at > (self.max_wait_minutes * 60):
                logger.warning(
                    f"Market {pending.market_slug} exceeded max wait time, "
                    f"using fallback resolution"
                )
                result = await self._fallback_resolution(pending)
                results.append(result)
                self.pending_resolutions.remove(pending)
                continue

            # Try to resolve via Gamma API
            try:
                result = await self._resolve_via_gamma(gamma_api_client, pending)
                if result:
                    results.append(result)
                    pending.resolved_at = current_time
                    pending.resolution_result = asdict(result)
                    logger.info(
                        f"Resolved market {pending.market_slug}: "
                        f"{result.outcome} (source: {result.source})"
                    )
                else:
                    # Not resolved yet, continue polling
                    continue

            except Exception as e:
                logger.error(f"Error resolving market {pending.market_slug}: {e}")
                # Try fallback
                result = await self._fallback_resolution(pending)
                results.append(result)
                pending.resolved_at = current_time
                pending.resolution_result = asdict(result)

        return results

    async def _resolve_via_gamma(
        self,
        gamma_api_client,
        pending: PendingResolution
    ) -> Optional[ResolutionResult]:
        """
        Try to resolve market via Gamma API

        Args:
            gamma_api_client: API client
            pending: Pending resolution

        Returns:
            ResolutionResult or None if not resolved
        """
        try:
            # Get market data from Gamma API
            response = await gamma_api_client.get(f"/markets/{pending.market_slug}")

            if not response or not response.get("data"):
                return None

            market_data = response["data"]

            # Check if market is closed
            if not market_data.get("closed", False):
                return None

            # Get outcome prices
            outcome_prices = market_data.get("outcomePrices")
            if not outcome_prices:
                return None

            # Determine winner
            won, outcome = self._determine_winner(outcome_prices, pending.position_data)

            return ResolutionResult(
                market_slug=pending.market_slug,
                condition_id=pending.condition_id,
                won=won,
                outcome=outcome,
                resolution_price=outcome_prices[0] if won else outcome_prices[1],
                timestamp=time.time(),
                source="gamma_api"
            )

        except Exception as e:
            logger.error(f"Gamma API resolution failed: {e}")
            return None

    async def _fallback_resolution(self, pending: PendingResolution) -> ResolutionResult:
        """
        Fallback resolution methods

        Args:
            pending: Pending resolution

        Returns:
            ResolutionResult
        """
        # Try Chainlink oracle fallback
        try:
            # Check position data for Chainlink info
            btc_anchor = pending.position_data.get("btc_anchor_price", 0)
            btc_current = pending.position_data.get("btc_current_price", 0)

            if btc_anchor > 0 and btc_current > 0:
                won, outcome = self._determine_via_chainlink(
                    btc_anchor, btc_current, pending.position_data
                )

                return ResolutionResult(
                    market_slug=pending.market_slug,
                    condition_id=pending.condition_id,
                    won=won,
                    outcome=outcome,
                    resolution_price=1.0 if won else 0.0,
                    timestamp=time.time(),
                    source="chainlink_oracle"
                )

        except Exception as e:
            logger.error(f"Chainlink fallback failed: {e}")

        # Final fallback: use last price threshold
        try:
            entry_price = pending.position_data.get("entry_price", 0.5)
            token_name = pending.position_data.get("token_name", "UP")

            # Legacy fallback: use last price threshold
            won = entry_price >= 0.70  # Old logic
            outcome = token_name if won else ("DOWN" if token_name == "UP" else "UP")

            return ResolutionResult(
                market_slug=pending.market_slug,
                condition_id=pending.condition_id,
                won=won,
                outcome=outcome,
                resolution_price=1.0 if won else 0.0,
                timestamp=time.time(),
                source="last_price_threshold"
            )

        except Exception as e:
            logger.error(f"All fallback methods failed: {e}")
            # Default to loss
            return ResolutionResult(
                market_slug=pending.market_slug,
                condition_id=pending.condition_id,
                won=False,
                outcome="UNKNOWN",
                resolution_price=0.0,
                timestamp=time.time(),
                source="unknown"
            )

    def _determine_winner(
        self,
        outcome_prices: List[float],
        position_data: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """
        Determine winner based on outcome prices

        Args:
            outcome_prices: [UP_price, DOWN_price]
            position_data: Position data

        Returns:
            Tuple of (won, outcome)
        """
        token_name = position_data.get("token_name", "UP")
        entry_price = position_data.get("entry_price", 0.5)

        # UP token wins if UP price > DOWN price
        if outcome_prices[0] > outcome_prices[1]:
            won = (token_name == "UP")
            outcome = "UP"
        else:
            won = (token_name == "DOWN")
            outcome = "DOWN"

        return won, outcome

    def _determine_via_chainlink(
        self,
        btc_anchor: float,
        btc_current: float,
        position_data: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """
        Determine winner using Chainlink oracle

        Args:
            btc_anchor: BTC price at market start
            btc_current: Current BTC price
            position_data: Position data

        Returns:
            Tuple of (won, outcome)
        """
        token_name = position_data.get("token_name", "UP")

        # UP wins if BTC went up
        btc_up = btc_current > btc_anchor
        won = (token_name == "UP") == btc_up

        outcome = "UP" if btc_up else "DOWN"

        return won, outcome

    def get_pending_count(self) -> int:
        """Get number of pending resolutions"""
        return len([p for p in self.pending_resolutions if p.resolved_at is None])

    def get_next_expiration(self) -> Optional[float]:
        """Get next expiration time"""
        pending = [p for p in self.pending_resolutions if p.resolved_at is None]
        if not pending:
            return None

        return min(p.end_time for p in pending)

    def save_pending_to_file(self, filepath: str) -> None:
        """Save pending resolutions to file"""
        try:
            data = {
                "pending_resolutions": [
                    {
                        "market_slug": p.market_slug,
                        "condition_id": p.condition_id,
                        "end_time": p.end_time,
                        "position_data": p.position_data,
                        "created_at": p.created_at,
                        "resolved_at": p.resolved_at,
                        "resolution_result": p.resolution_result
                    }
                    for p in self.pending_resolutions
                ],
                "markets_seen": list(self.markets_seen),
                "trade_number": self.trade_number
            }

            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)

            logger.info(f"Saved {len(self.pending_resolutions)} pending resolutions to {filepath}")

        except Exception as e:
            logger.error(f"Error saving pending resolutions: {e}")

    def load_pending_from_file(self, filepath: str) -> None:
        """Load pending resolutions from file"""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)

            for p_data in data.get("pending_resolutions", []):
                pending = PendingResolution(
                    market_slug=p_data["market_slug"],
                    condition_id=p_data["condition_id"],
                    end_time=p_data["end_time"],
                    position_data=p_data["position_data"],
                    created_at=p_data["created_at"],
                    resolved_at=p_data.get("resolved_at"),
                    resolution_result=p_data.get("resolution_result")
                )
                self.pending_resolutions.append(pending)

            self.markets_seen = set(data.get("markets_seen", []))
            self.trade_number = data.get("trade_number", 0)

            logger.info(f"Loaded {len(self.pending_resolutions)} pending resolutions from {filepath}")

        except Exception as e:
            logger.error(f"Error loading pending resolutions: {e}")

    def create_trade_record(
        self,
        pending: PendingResolution,
        resolution: ResolutionResult
    ) -> Dict[str, Any]:
        """
        Create trade record for resolved position

        Args:
            pending: Pending resolution
            resolution: Resolution result

        Returns:
            Trade record dictionary
        """
        # Extract position data
        pos_data = pending.position_data

        # Calculate P&L
        contracts = pos_data.get("contracts", 0)
        entry_price = pos_data.get("entry_price", 0.0)
        hedge_contracts = pos_data.get("hedged", False)

        entry_cost = contracts * entry_price
        hedge_cost = 0.0
        hedge_payout = 0.0

        if hedge_contracts:
            hedge_cost = pos_data.get("hedge_contracts", 0) * pos_data.get("hedge_price", 0.0)
            if not resolution.won:
                hedge_payout = pos_data.get("hedge_contracts", 0) * 1.00

        if resolution.won:
            pnl = (contracts - entry_cost) - hedge_cost
        else:
            pnl = (-entry_cost - hedge_cost) + hedge_payout

        # Calculate drawdown
        min_price_seen = pos_data.get("min_price_seen", entry_price)
        dd_abs = max(0.0, entry_price - min_price_seen)
        dd_pct = (dd_abs / entry_price * 100) if entry_price > 0 else 0.0

        # Create trade record
        record = {
            "market_slug": pending.market_slug,
            "token_name": pos_data.get("token_name"),
            "entry_price": entry_price,
            "exit_price": 1.0 if resolution.won else 0.0,
            "contracts": contracts,
            "pnl": pnl,
            "won": resolution.won,
            "timestamp": resolution.timestamp,
            "max_drawdown_abs": dd_abs,
            "max_drawdown_pct": dd_pct,
            "hedged": hedge_contracts,
            "hedge_contracts": pos_data.get("hedge_contracts", 0),
            "hedge_price": pos_data.get("hedge_price", 0.0),
            "resolution_source": resolution.source,
            "outcome": resolution.outcome,
            "btc_anchor_price": pos_data.get("btc_anchor_price"),
            "btc_current_price": pos_data.get("btc_current_price"),
            "trade_number": self.trade_number
        }

        # Increment trade number
        self.trade_number += 1

        return record