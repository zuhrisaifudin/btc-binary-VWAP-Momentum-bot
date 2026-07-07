"""
Smart Scaling Engine for Polymarket BTC Binary Bot
Implements maker-first scaling with intelligent fallbacks
"""

import asyncio
import logging
import time
import random
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from src.regime_strategy import OrderExecutor, ExecutionConfig
from src.order_executor import OrderArgs
from py_clob_client_v2.clob_types import OrderType
from py_clob_client_v2.order_builder.constants import BUY, SELL

logger = logging.getLogger("btc_live.smart_scaling")

@dataclass
class ScalingConfig:
    """Configuration for smart scaling"""
    parts: int = 10
    total_duration_sec: float = 120.0
    initial_offset_usd: float = 0.01
    offset_increment_usd: float = 0.005
    max_spread_usd: float = 0.05
    taker_fallback_start: int = 8  # Start taker fallback at this slice
    simulation_fill_probability_base: float = 0.7
    simulation_partial_fill_prob: float = 0.3
    max_contracts: int = 999999

@dataclass
class ScalingResult:
    """Result from scaling execution"""
    success: bool
    avg_price: float
    contracts_filled: int
    total_cost: float
    slices_executed: int
    maker_fills: int
    taker_fills: int

class SmartScalingEngine:
    """
    Smart scaling engine with maker-first pricing and intelligent fallbacks
    """

    def __init__(
        self,
        executor: OrderExecutor,
        config: ScalingConfig = None
    ):
        self.executor = executor
        self.config = config or ScalingConfig()

    def calculate_maker_price(
        self,
        side: str,
        best_bid: float,
        best_ask: float,
        slice_index: int
    ) -> float:
        """
        Calculate maker price with intelligent offset

        Args:
            side: "BUY" or "SELL"
            best_bid: Best bid price
            best_ask: Best ask price
            slice_index: Index of current slice (0 to parts-1)

        Returns:
            Maker limit price
        """
        # Calculate offset with increment
        offset = (
            self.config.initial_offset_usd +
            (slice_index * self.config.offset_increment_usd)
        )

        if side == BUY:
            # Buy: place at best_bid + offset, but not above best_ask
            price = best_bid + offset
            # Don't chase the ask
            return min(price, best_ask - 0.001)
        else:  # SELL
            # Sell: place at best_ask - offset, but not below best_bid
            price = best_ask - offset
            # Don't drop below the bid
            return max(price, best_bid + 0.001)

    def check_spread(self, best_bid: float, best_ask: float) -> bool:
        """Check if spread is acceptable"""
        spread = best_ask - best_bid
        return spread <= self.config.max_spread_usd

    def simulate_fill_probability(
        self,
        side: str,
        limit_price: float,
        best_bid: float,
        best_ask: float
    ) -> float:
        """
        Calculate fill probability in simulation mode
        """
        if not self.executor.simulation_mode:
            return 1.0  # Always fill in live mode

        if side == BUY:
            # Distance from best_ask (how aggressive the bid is)
            distance = best_ask - limit_price
            # Closer to best_ask = higher fill probability
            fill_prob = max(0.3, 1.0 - (distance * 10))
        else:  # SELL
            # Distance from best_bid
            distance = limit_price - best_bid
            # Closer to best_bid = higher fill probability
            fill_prob = max(0.3, 1.0 - (distance * 10))

        return fill_prob

    def simulate_fill(
        self,
        side: str,
        contracts: int,
        fill_prob: float
    ) -> int:
        """
        Simulate order fill
        """
        if random.random() < fill_prob:
            # Full or partial fill
            if random.random() < 0.7:  # 70% chance of full fill
                return contracts
            else:  # 30% chance of partial fill
                return max(1, contracts // 2)
        else:
            return 0

    async def scale_in(
        self,
        token_id: str,
        total_budget: float,
        side: str = "BUY",
        target_price: float = None
    ) -> ScalingResult:
        """
        Execute smart scaling-in with maker-first pricing

        Args:
            token_id: Token ID to trade
            total_budget: Total USD budget for scaling
            side: "BUY" or "SELL"
            target_price: Target price for reference

        Returns:
            ScalingResult with execution details
        """
        slice_budget = total_budget / self.config.parts
        interval = self.config.total_duration_sec / self.config.parts

        contracts_filled = 0
        total_cost = 0.0
        slices_executed = 0
        maker_fills = 0
        taker_fills = 0

        logger.info(
            f"Starting smart scaling-in: token={token_id[:10]}... "
            f"budget=${total_budget:.2f}, parts={self.config.parts}, "
            f"duration={self.config.total_duration_sec:.1f}s"
        )

        for i in range(self.config.parts):
            slices_executed += 1

            # Get current order book state
            book_data = await self.executor.get_order_book(token_id)
            if not book_data:
                logger.warning(f"No order book data for token {token_id}")
                await asyncio.sleep(interval)
                continue

            best_bid = book_data.get("best_bid", 0.0)
            best_ask = book_data.get("best_ask", 0.0)

            # Check spread
            if not self.check_spread(best_bid, best_ask):
                logger.warning(
                    f"Spread too wide: {best_ask - best_bid:.4f} > "
                    f"{self.config.max_spread_usd:.4f}, skipping slice {i+1}"
                )
                continue

            # Calculate maker price
            limit_price = self.calculate_maker_price(
                side, best_bid, best_ask, i
            )

            # Calculate contracts to trade
            if side == BUY:
                contracts = int(slice_budget / limit_price)
            else:  # SELL
                # For sell, use minimum of slice_budget/price and max_contracts
                contracts = min(
                    int(slice_budget / limit_price),
                    self.config.max_contracts
                )

            if contracts < 1:
                logger.warning(
                    f"Contracts too small ({contracts}), skipping slice {i+1}"
                )
                continue

            # Determine fill method
            use_taker = i >= self.config.taker_fallback_start

            if self.executor.simulation_mode:
                # Simulate fill
                fill_prob = self.simulate_fill_probability(
                    side, limit_price, best_bid, best_ask
                )
                filled_contracts = self.simulate_fill(
                    side, contracts, fill_prob
                )

                if filled_contracts > 0:
                    total_cost += filled_contracts * limit_price
                    contracts_filled += filled_contracts
                    maker_fills += 1

                logger.info(
                    f"Slice {i+1}/{self.config.parts}: "
                    f"Simulated fill: {filled_contracts}/{contracts} "
                    f"at ${limit_price:.4f}"
                )

            elif use_taker:
                # Taker order - market order
                try:
                    if side == BUY:
                        signed_order = await asyncio.to_thread(
                            self.executor._client.create_market_order,
                            OrderArgs(
                                price=0.0,  # Market order
                                size=contracts,
                                side=BUY,
                                token_id=token_id
                            )
                        )
                    else:  # SELL
                        signed_order = await asyncio.to_thread(
                            self.executor._client.create_market_order,
                            OrderArgs(
                                price=0.0,  # Market order
                                size=contracts,
                                side=SELL,
                                token_id=token_id
                            )
                        )

                    # Execute order
                    response = await asyncio.to_thread(
                        self.executor._client.post_order,
                        signed_order,
                        OrderType.MARKET
                    )

                    if response and response.get("success", False):
                        filled_contracts = contracts
                        total_cost += filled_contracts * limit_price
                        contracts_filled += filled_contracts
                        taker_fills += 1

                        logger.info(
                            f"Slice {i+1}/{self.config.parts}: "
                            f"Taker filled: {filled_contracts} "
                            f"at ~${limit_price:.4f}"
                        )

                except Exception as e:
                    logger.error(f"Error in taker order: {e}")

            else:
                # Maker order - limit order
                try:
                    # Create limit order
                    if side == BUY:
                        signed_order = await asyncio.to_thread(
                            self.executor._client.create_order,
                            OrderArgs(
                                price=limit_price,
                                size=contracts,
                                side=BUY,
                                token_id=token_id
                            )
                        )
                    else:  # SELL
                        signed_order = await asyncio.to_thread(
                            self.executor._client.create_order,
                            OrderArgs(
                                price=limit_price,
                                size=contracts,
                                side=SELL,
                                token_id=token_id
                            )
                        )

                    # Post GTC order
                    response = await asyncio.to_thread(
                        self.executor._client.post_order,
                        signed_order,
                        OrderType.GTC
                    )

                    if response and response.get("success", False):
                        logger.info(
                            f"Slice {i+1}/{self.config.parts}: "
                            f"Maker placed: {contracts} "
                            f"at ${limit_price:.4f}"
                        )

                        # Wait for fill with timeout
                        start_time = time.time()
                        timeout = 2.0  # 2 second timeout per order
                        filled_contracts = 0

                        while time.time() - start_time < timeout:
                            fills = await self.executor.get_order_fills(response.get("id"))
                            if fills > 0:
                                filled_contracts = fills
                                total_cost += filled_contracts * limit_price
                                contracts_filled += filled_contracts
                                maker_fills += 1
                                break

                            await asyncio.sleep(0.1)

                        # Cancel unfilled portion
                        remaining = contracts - filled_contracts
                        if remaining > 0:
                            try:
                                await asyncio.to_thread(
                                    self.executor._client.cancel_order,
                                    response.get("id")
                                )
                            except Exception as e:
                                logger.warning(f"Error canceling order: {e}")

                except Exception as e:
                    logger.error(f"Error in maker order: {e}")

            # Sleep before next slice
            await asyncio.sleep(interval)

        # Calculate results
        avg_price = total_cost / contracts_filled if contracts_filled > 0 else 0.0
        success = contracts_filled > 0

        logger.info(
            f"Scaling complete: success={success}, "
            f"filled={contracts_filled}, avg_price=${avg_price:.4f}, "
            f"cost=${total_cost:.2f}, maker={maker_fills}, taker={taker_fills}"
        )

        return ScalingResult(
            success=success,
            avg_price=avg_price,
            contracts_filled=contracts_filled,
            total_cost=total_cost,
            slices_executed=slices_executed,
            maker_fills=maker_fills,
            taker_fills=taker_fills
        )