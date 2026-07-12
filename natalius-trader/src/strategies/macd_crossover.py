"""
MACD Crossover Strategy

Classic momentum strategy based on MACD indicator crossovers.
"""

from typing import Optional, Dict, Any
from loguru import logger
from .base_strategy import BaseStrategy


class MACDCrossover(BaseStrategy):
    """
    MACD Crossover Strategy
    
    Generates signals when:
    - BUY: MACD line crosses above Signal line
    - SELL: MACD line crosses below Signal line
    """
    
    def __init__(
        self, 
        symbol: str,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
        config: Optional[Dict] = None
    ):
        super().__init__(
            name="MACD_Crossover",
            symbol=symbol,
            config=config
        )
        
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        
        self.prev_macd = None
        self.prev_signal = None
        self.macd_history = []
        
    async def on_start(self):
        """Initialize strategy on start"""
        logger.info(f"MACD Strategy started for {self.symbol}")
        logger.info(f"Parameters: fast={self.fast_period}, slow={self.slow_period}, signal={self.signal_period}")
        
    async def on_stop(self):
        """Cleanup on stop"""
        logger.info(f"MACD Strategy stopped for {self.symbol}")
        self.macd_history.clear()
        
    async def generate_signal(self) -> Optional[Dict[str, Any]]:
        """
        Generate trading signal based on MACD crossover
        
        Returns:
            Signal dictionary or None if no signal
        """
        # Get latest MACD values (would be calculated from market data)
        current_macd = self._calculate_macd()
        current_signal = self._calculate_signal_line()
        
        if current_macd is None or current_signal is None:
            return None
            
        signal = None
        
        # Check for bullish crossover (MACD crosses above Signal)
        if (self.prev_macd and self.prev_signal and 
            self.prev_macd <= self.prev_signal and 
            current_macd > current_signal):
            
            signal = {
                "action": "BUY",
                "quantity": self.config.get("quantity", 0.001),
                "metadata": {
                    "macd": current_macd,
                    "signal_line": current_signal,
                    "histogram": current_macd - current_signal
                }
            }
            logger.info(f"BUY signal generated for {self.symbol}")
            
        # Check for bearish crossover (MACD crosses below Signal)
        elif (self.prev_macd and self.prev_signal and
              self.prev_macd >= self.prev_signal and
              current_macd < current_signal):
              
            signal = {
                "action": "SELL",
                "quantity": self.config.get("quantity", 0.001),
                "metadata": {
                    "macd": current_macd,
                    "signal_line": current_signal,
                    "histogram": current_macd - current_signal
                }
            }
            logger.info(f"SELL signal generated for {self.symbol}")
            
        # Update previous values
        self.prev_macd = current_macd
        self.prev_signal = current_signal
        
        return signal
        
    async def on_fill(self, order: Dict):
        """Handle order fill"""
        logger.info(f"Order filled: {order}")
        
    async def on_cancel(self, order_id: str):
        """Handle order cancellation"""
        logger.info(f"Order cancelled: {order_id}")
        
    def _calculate_macd(self) -> Optional[float]:
        """
        Calculate MACD value
        In production, this would use actual price data
        """
        # Placeholder - would calculate from EMA(12) - EMA(26)
        return None
        
    def _calculate_signal_line(self) -> Optional[float]:
        """
        Calculate Signal line (EMA of MACD)
        In production, this would use actual MACD history
        """
        # Placeholder - would calculate EMA(9) of MACD
        return None
