"""
Natalius Trader Strategies Module

Available strategies:
- BaseStrategy: Abstract base class for all strategies
- MACDCrossover: Classic MACD crossover strategy
- RSIScalping: RSI-based scalping strategy (coming soon)
- NataliusCustom: Custom proprietary strategy (coming soon)
"""

from .base_strategy import BaseStrategy
from .macd_crossover import MACDCrossover

__all__ = [
    "BaseStrategy",
    "MACDCrossover"
]
