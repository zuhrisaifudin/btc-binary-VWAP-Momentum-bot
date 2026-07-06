import logging
import math
import numpy as np
import asyncio
import time
from typing import List, Tuple, Optional, Dict
from py_clob_client_v2.clob_types import OrderArgs, OrderType
from py_clob_client_v2.order_builder.constants import BUY
from src.order_executor import OrderExecutor, ExecutionConfig

logger = logging.getLogger("btc_live.regime")

class HurstExponentCalculator:
    """
    Calculates the Hurst Exponent (H) using Rescaled Range (R/S) analysis.
    H > 0.55: Persistent / Trending.
    H < 0.45: Anti-persistent / Mean Reverting.
    0.45 <= H <= 0.55: Random Walk / Neutral.
    """
    @staticmethod
    def calculate(prices: List[float]) -> float:
        """
        Calculates the Hurst Exponent of a price series.
        """
        if len(prices) < 20:
            return 0.5  # Neutral default for small datasets
            
        try:
            # Convert to log returns
            prices_arr = np.array(prices)
            returns = np.diff(np.log(prices_arr))
            N = len(returns)
            
            # We want to evaluate different lags
            # Lags should be reasonable powers of 2 or sub-intervals
            max_lag = int(math.floor(N / 2))
            if max_lag < 8:
                return 0.5
                
            lags = []
            rs_values = []
            
            # Generate lags e.g. N/2, N/4, N/8... down to 8
            lag = max_lag
            while lag >= 8:
                lags.append(lag)
                # Compute R/S for this lag
                rs_vals_for_lag = []
                for start in range(0, N - lag + 1, lag):
                    subset = returns[start : start + lag]
                    if len(subset) < 8:
                        continue
                    mean = np.mean(subset)
                    y = subset - mean
                    z = np.cumsum(y)
                    r = np.max(z) - np.min(z)
                    s = np.std(subset)
                    if s > 0:
                        rs_vals_for_lag.append(r / s)
                        
                if rs_vals_for_lag:
                    rs_values.append(np.mean(rs_vals_for_lag))
                else:
                    lags.pop() # Remove lag if no R/S computed
                lag = int(math.floor(lag / 2))
                
            if len(lags) < 2:
                return 0.5
                
            # Perform linear regression on log(lags) vs log(R/S)
            poly = np.polyfit(np.log(lags), np.log(rs_values), 1)
            H = poly[0]
            
            # Clip between 0 and 1 theoretically
            return float(np.clip(H, 0.0, 1.0))
            
        except Exception as e:
            logger.error(f"Error calculating Hurst Exponent: {e}")
            return 0.5

class OrderFlowImbalanceCalculator:
    """
    Computes Order Flow Imbalance (OFI) from order book updates.
    """
    def __init__(self):
        self.last_bid_price: Optional[float] = None
        self.last_bid_size: Optional[float] = None
        self.last_ask_price: Optional[float] = None
        self.last_ask_size: Optional[float] = None
        self.ofi: float = 0.0
        
    def update(self, bid_price: float, bid_size: float, ask_price: float, ask_size: float) -> float:
        """
        Updates with the current L1 book state and returns the instant OFI.
        """
        if self.last_bid_price is None:
            self.last_bid_price = bid_price
            self.last_bid_size = bid_size
            self.last_ask_price = ask_price
            self.last_ask_size = ask_size
            return 0.0
            
        # Delta Bid volume calculation
        if bid_price > self.last_bid_price:
            delta_v_bid = bid_size
        elif bid_price == self.last_bid_price:
            delta_v_bid = bid_size - self.last_bid_size
        else:
            delta_v_bid = 0.0
            
        # Delta Ask volume calculation
        if ask_price < self.last_ask_price:
            delta_v_ask = ask_size
        elif ask_price == self.last_ask_price:
            delta_v_ask = ask_size - self.last_ask_size
        else:
            delta_v_ask = 0.0
            
        # Update cache
        self.last_bid_price = bid_price
        self.last_bid_size = bid_size
        self.last_ask_price = ask_price
        self.last_ask_size = ask_size
        
        self.ofi = delta_v_bid - delta_v_ask
        return self.ofi

    def update_multi_level(self, bids: List[Dict[str, Any]], asks: List[Dict[str, Any]]) -> float:
        """
        Calculates OFI using the top 3 levels of the order book.
        """
        if not bids or not asks:
            return 0.0
        # Sort bids descending, asks ascending
        sorted_bids = sorted(bids, key=lambda x: float(x["price"]), reverse=True)[:3]
        sorted_asks = sorted(asks, key=lambda x: float(x["price"]))[:3]
        
        best_bid_price = float(sorted_bids[0]["price"])
        total_bid_size = sum(float(x["size"]) for x in sorted_bids)
        
        best_ask_price = float(sorted_asks[0]["price"])
        total_ask_size = sum(float(x["size"]) for x in sorted_asks)
        
        return self.update(best_bid_price, total_bid_size, best_ask_price, total_ask_size)

class RegimeDetector:
    """
    Detects market regime (Trending vs Mean Reverting vs Neutral)
    based on Hurst Exponent and OFI.
    """
    @staticmethod
    def detect(hurst: float, ofi_ma: float) -> str:
        """
        Determines the current regime.
        ofi_ma: Moving Average of OFI to smooth the high-frequency updates.
        """
        if hurst > 0.55:
            return "TRENDING"
        elif hurst < 0.45:
            return "MEAN_REVERTING"
        else:
            return "NEUTRAL"

class KellyCriterionCalculator:
    """
    Calculates modified Kelly Criterion allocations for binary options.
    """
    @staticmethod
    def calculate(win_prob: float, price: float, half_kelly: bool = True) -> float:
        """
        f* = (p * (1 - P) - (1 - p) * P) / (P * (1 - P)) = (p - P) / (P * (1 - P))
        """
        if price <= 0.01 or price >= 0.99:
            return 0.0
            
        # Clip probability to reasonable bounds
        p = np.clip(win_prob, 0.01, 0.99)
        P = price
        
        f_star = (p - P) / (P * (1.0 - P))
        
        # Don't place negative allocations (e.g. if we shouldn't buy)
        if f_star < 0:
            return 0.0
            
        if half_kelly:
            f_star *= 0.5
            
        return float(np.clip(f_star, 0.0, 1.0))

class ScalingExecutionEngine:
    """
    Execution engine that implements a smart maker-only limit scaling-in logic.
    Splits orders into N slices time-weighted over 120 seconds.
    """
    def __init__(self, executor: OrderExecutor):
        self.executor = executor
        
    async def scale_in(
        self,
        token_id: str,
        total_budget: float,
        target_price: float,
        side: str = "BUY",
        parts: int = 10,
        total_duration_sec: float = 120.0
    ) -> Tuple[bool, float, int]:
        """
        Executes a smart scaling-in over the given duration.
        """
        slice_budget = total_budget / parts
        interval = total_duration_sec / parts
        contracts_filled = 0
        total_cost = 0.0
        
        logger.info(f"Starting scaling-in execution for token={token_id[:10]}... budget=${total_budget:.2f} slices={parts} interval={interval:.1f}s")
        
        for i in range(parts):
            # Check price dynamically at each slice
            best_ask = await self.executor.get_best_ask(token_id)
            if not best_ask:
                best_ask = target_price
                
            # Place order on the bid/ask side as a maker
            logger.info(f"Scaling slice {i+1}/{parts}: placing limit order at ${best_ask:.4f} for budget ${slice_budget:.2f}")
            
            contracts = int(math.floor(slice_budget / best_ask))
            if contracts < 1:
                contracts = 1
                
            if self.executor.simulation_mode:
                # Simulate fill at current ask price
                contracts_filled += contracts
                total_cost += contracts * best_ask
            else:
                try:
                    # Place standard limit order (GTC)
                    signed_order = await asyncio.to_thread(
                        self.executor._client.create_order,
                        OrderArgs(
                            price=best_ask,
                            size=contracts,
                            side=BUY,
                            token_id=token_id
                        )
                    )
                    response = await asyncio.to_thread(
                        self.executor._client.post_order,
                        signed_order,
                        OrderType.GTC
                    )
                    if isinstance(response, dict) and response.get("success", False):
                        contracts_filled += contracts
                        total_cost += contracts * best_ask
                except Exception as e:
                    logger.error(f"Error during scaling-in slice {i+1}: {e}")
                    
            await asyncio.sleep(interval)
            
        success = contracts_filled > 0
        avg_price = (total_cost / contracts_filled) if contracts_filled > 0 else 0.0
        return success, avg_price, contracts_filled
