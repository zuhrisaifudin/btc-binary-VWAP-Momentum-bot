#!/usr/bin/env python3
"""
Test suite for indicators module.

Tests VWAP, momentum, z-score, and deviation calculations.
"""

import unittest
import math
import time
from collections import deque
from datetime import datetime, timezone

from src.indicators import (
    calc_vwap,
    calc_momentum,
    calc_zscore,
    calc_deviation,
    WinRateTable,
    Trade
)


class TestIndicators(unittest.TestCase):
    """Test indicator calculations."""

    def setUp(self):
        """Set up test data."""
        # Sample trade data
        self.trades_up = [
            Trade(price=0.50, volume=10, timestamp=1000),
            Trade(price=0.55, volume=20, timestamp=1100),
            Trade(price=0.52, volume=15, timestamp=1200),
            Trade(price=0.58, volume=25, timestamp=1300),
            Trade(price=0.60, volume=30, timestamp=1400),
        ]

        self.trades_down = [
            Trade(price=0.50, volume=10, timestamp=1000),
            Trade(price=0.45, volume=20, timestamp=1100),
            Trade(price=0.48, volume=15, timestamp=1200),
            Trade(price=0.42, volume=25, timestamp=1300),
            Trade(price=0.40, volume=30, timestamp=1400),
        ]

    def test_calc_vwap(self):
        """Test VWAP calculation."""
        # Test with sample UP trades (volume -> size)
        vwap = calc_vwap(self.trades_up)
        expected = (0.50*10 + 0.55*20 + 0.52*15 + 0.58*25 + 0.60*30) / (10+20+15+25+30)
        self.assertAlmostEqual(vwap, expected, places=6)

        # Test empty list
        self.assertEqual(calc_vwap([]), 0.0)

    def test_calc_momentum_none_case(self):
        """Test momentum calculation with None cases."""
        # Test with empty deque
        empty_deque = deque()
        self.assertIsNone(calc_momentum(empty_deque, 0.50))

        # Test with insufficient data
        small_deque = deque([Trade(price=0.50, volume=10, timestamp=1000)])
        self.assertIsNone(calc_momentum(small_deque, 0.50))

    def test_calc_momentum(self):
        """Test momentum calculation."""
        # Create deque with trades
        trades_deque = deque(self.trades_up)

        # Test momentum calculation - returns None when no historical data
        momentum = calc_momentum(trades_deque, 0.62)
        self.assertIsNone(momentum)  # No trades in the 90s-105s window

    def test_calc_zscore(self):
        """Test z-score calculation."""
        # Create deque with Trade objects
        trades = deque([
            Trade(price=0.50, volume=10, timestamp=time.time() - 4),
            Trade(price=0.55, volume=10, timestamp=time.time() - 3),
            Trade(price=0.52, volume=10, timestamp=time.time() - 2),
            Trade(price=0.58, volume=10, timestamp=time.time() - 1),
        ])
        current_price = 0.62

        zscore = calc_zscore(trades, current_price)
        self.assertIsNotNone(zscore)
        self.assertIsInstance(zscore, float)

        # Test with empty deque
        self.assertEqual(calc_zscore(deque(), current_price), 0.0)

    def test_calc_deviation(self):
        """Test deviation calculation."""
        # Test positive deviation (should be percentage)
        vwap = 0.50
        current_price = 0.55
        deviation = calc_deviation(current_price, vwap)
        # Should be 10% not 0.10
        self.assertAlmostEqual(deviation, 10.0, places=6)

        # Test negative deviation
        deviation = calc_deviation(0.45, vwap)
        self.assertAlmostEqual(deviation, -10.0, places=6)

        # Test zero deviation
        deviation = calc_deviation(vwap, vwap)
        self.assertEqual(deviation, 0.0)

    def test_winrate_table_initialization(self):
        """Test WinRateTable initialization."""
        table = WinRateTable("data/win_rate.csv")
        self.assertIsNotNone(table)
        # Additional tests depend on the actual CSV data

    def test_winrate_table_get_winrate(self):
        """Test WinRateTable get_winrate method."""
        table = WinRateTable("data/win_rate.csv")

        # Test normal case (assuming CSV has data)
        winrate = table.get_winrate(0.65, 0, 15)  # price=0.65, minute=0, interval=15
        # Expected result depends on actual CSV data
        if winrate is not None:
            self.assertGreaterEqual(winrate, 0.0)
            self.assertLessEqual(winrate, 1.0)


class TestTrade(unittest.TestCase):
    """Test Trade dataclass."""

    def test_trade_creation(self):
        """Test Trade creation."""
        trade = Trade(price=0.50, volume=10, timestamp=1000)

        self.assertEqual(trade.price, 0.50)
        self.assertEqual(trade.volume, 10)
        self.assertEqual(trade.timestamp, 1000)


if __name__ == '__main__':
    unittest.main()