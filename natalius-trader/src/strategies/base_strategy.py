"""
Base Strategy Class - All strategies should inherit from this

Provides:
- Common interface for all strategies
- Signal generation framework
- Risk parameter handling
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from datetime import datetime
from loguru import logger


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    
    All custom strategies must inherit from this class and implement
    the required methods.
    """
    
    def __init__(self, name: str, symbol: str, config: Optional[Dict] = None):
        self.name = name
        self.symbol = symbol
        self.config = config or {}
        self.is_active = False
        self.created_at = datetime.now()
        
        logger.info(f"Strategy '{name}' initialized for {symbol}")
        
    @abstractmethod
    async def on_start(self):
        """Called when strategy is started"""
        pass
        
    @abstractmethod
    async def on_stop(self):
        """Called when strategy is stopped"""
        pass
        
    @abstractmethod
    async def generate_signal(self) -> Optional[Dict[str, Any]]:
        """
        Generate trading signal based on current market data
        
        Returns:
            Signal dictionary with keys:
            - action: 'BUY', 'SELL', 'HOLD'
            - quantity: amount to trade
            - price: optional limit price
            - stop_loss: optional stop loss price
            - take_profit: optional take profit price
            - metadata: additional strategy-specific data
        """
        pass
        
    @abstractmethod
    async def on_fill(self, order: Dict):
        """Called when an order is filled"""
        pass
        
    @abstractmethod
    async def on_cancel(self, order_id: str):
        """Called when an order is cancelled"""
        pass
        
    def activate(self):
        """Activate the strategy"""
        self.is_active = True
        logger.info(f"Strategy '{self.name}' activated")
        
    def deactivate(self):
        """Deactivate the strategy"""
        self.is_active = False
        logger.info(f"Strategy '{self.name}' deactivated")
        
    def get_parameters(self) -> Dict:
        """Get strategy parameters for logging/monitoring"""
        return {
            "name": self.name,
            "symbol": self.symbol,
            "is_active": self.is_active,
            "config": self.config
        }
