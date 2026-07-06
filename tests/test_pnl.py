#!/usr/bin/env python3
"""
Test suite for P&L calculations.

Tests position closing, win/loss scenarios, hedge considerations, and resolution tracking.
"""

import unittest
import time
from unittest.mock import patch

from src.stats import TradingStats, Position, TradeRecord


class TestTradingStats(unittest.TestCase):
    """Test TradingStats class and P&L calculations."""

    def setUp(self):
        """Set up test fixtures."""
        self.stats = TradingStats("test_trading_log.json")

    def tearDown(self):
        """Clean up test fixtures."""
        import os
        if os.path.exists("test_trading_log.json"):
            os.remove("test_trading_log.json")

    def test_position_creation(self):
        """Test Position creation."""
        position = Position(
            token_name="UP",
            token_id="test-up-token",
            opposite_token_id="test-down-token",
            entry_price=0.50,
            contracts=10,
            entry_time=time.time(),
            market_slug="test-market",
            min_price_seen=0.50
        )

        self.assertEqual(position.token_name, "UP")
        self.assertEqual(position.contracts, 10)
        self.assertEqual(position.entry_price, 0.50)
        self.assertFalse(position.hedged)
        self.assertEqual(position.min_price_seen, 0.50)

    @patch('main.time.time')
    def test_close_position_win(self, mock_time):
        """Test position close - win scenario."""
        mock_time.return_value = time.time() + 3600  # 1 hour later

        # Create position
        position = Position(
            token_name="UP",
            token_id="test-up-token",
            opposite_token_id="test-down-token",
            entry_price=0.50,
            contracts=10,
            entry_time=time.time(),
            market_slug="test-market",
            min_price_seen=0.50
        )

        # Set position
        self.stats.position = position

        # Close position as win
        record = self.stats.close_position(won=True, resolution_source="gamma_outcome")

        # Verify record
        self.assertIsNotNone(record)
        self.assertEqual(record.won, True)
        self.assertEqual(record.resolution_source, "gamma_outcome")
        self.assertEqual(record.contracts, 10)
        # Expected P&L: 10 * (1 - 0.50) = $5.00
        self.assertAlmostEqual(record.pnl, 5.00, places=2)
        self.assertIsNone(self.stats.position)  # Position should be closed

    @patch('main.time.time')
    def test_close_position_loss(self, mock_time):
        """Test position close - loss scenario."""
        mock_time.return_value = time.time() + 3600

        # Create position
        position = Position(
            token_name="UP",
            token_id="test-up-token",
            opposite_token_id="test-down-token",
            entry_price=0.70,
            contracts=5,
            entry_time=time.time(),
            market_slug="test-market",
            min_price_seen=0.70
        )

        # Set position
        self.stats.position = position

        # Close position as loss
        record = self.stats.close_position(won=False, resolution_source="gamma_outcome")

        # Verify record
        self.assertIsNotNone(record)
        self.assertEqual(record.won, False)
        self.assertEqual(record.resolution_source, "gamma_outcome")
        self.assertEqual(record.contracts, 5)
        # Expected P&L: -5 * 0.70 = -$3.50
        self.assertAlmostEqual(record.pnl, -3.50, places=2)
        self.assertIsNone(self.stats.position)

    @patch('main.time.time')
    def test_close_position_with_hedge_win(self, mock_time):
        """Test position close - win with hedge."""
        mock_time.return_value = time.time() + 3600

        # Create position with hedge
        position = Position(
            token_name="UP",
            token_id="test-up-token",
            opposite_token_id="test-down-token",
            entry_price=0.60,
            contracts=8,
            entry_time=time.time(),
            market_slug="test-market",
            min_price_seen=0.60,
            hedged=True,
            hedge_contracts=3,
            hedge_price=0.40
        )

        # Set position
        self.stats.position = position

        # Close position as win (hedge loses)
        record = self.stats.close_position(won=True, resolution_source="gamma_outcome")

        # Verify record
        self.assertIsNotNone(record)
        self.assertEqual(record.won, True)
        self.assertTrue(record.hedged)
        # Expected P&L: (8 - 8*0.60) - (3*0.40) = (8-4.8) - 1.2 = $2.00
        self.assertAlmostEqual(record.pnl, 2.00, places=2)

    @patch('main.time.time')
    def test_close_position_with_hedge_loss(self, mock_time):
        """Test position close - loss with hedge."""
        mock_time.return_value = time.time() + 3600

        # Create position with hedge
        position = Position(
            token_name="UP",
            token_id="test-up-token",
            opposite_token_id="test-down-token",
            entry_price=0.80,
            contracts=5,
            entry_time=time.time(),
            market_slug="test-market",
            min_price_seen=0.80,
            hedged=True,
            hedge_contracts=2,
            hedge_price=0.30
        )

        # Set position
        self.stats.position = position

        # Close position as loss (hedge wins)
        record = self.stats.close_position(won=False, resolution_source="gamma_outcome")

        # Verify record
        self.assertIsNotNone(record)
        self.assertEqual(record.won, False)
        self.assertTrue(record.hedged)
        # Expected P&L: (-5*0.80 - 2*0.30) + (2*1.00) = (-4 - 0.6) + 2 = -$2.60
        self.assertAlmostEqual(record.pnl, -2.60, places=2)

    @patch('main.time.time')
    def test_close_position_backward_compatibility(self, mock_time):
        """Test backward compatibility with old close_position signature."""
        mock_time.return_value = time.time() + 3600

        # Create position
        position = Position(
            token_name="UP",
            token_id="test-up-token",
            opposite_token_id="test-down-token",
            entry_price=0.50,
            contracts=4,
            entry_time=time.time(),
            market_slug="test-market",
            min_price_seen=0.50
        )

        # Set position
        self.stats.position = position

        # Old style - passing final price (should trigger legacy logic)
        record = self.stats.close_position(0.75)  # Above 0.70 threshold

        # Verify record (should be win with legacy source)
        self.assertIsNotNone(record)
        if isinstance(record, tuple):
            record, pnl = record
        self.assertEqual(record.won, True)  # 0.75 >= 0.70
        self.assertEqual(record.resolution_source, "preliminary_last_price")
        # Expected P&L with legacy logic: different from actual outcome
        # This shows why we need the new system

    def test_awaiting_resolution_flag(self):
        """Test awaiting_resolution flag functionality."""
        # Create position with awaiting_resolution flag
        position = Position(
            token_name="DOWN",
            token_id="test-down-token",
            opposite_token_id="test-up-token",
            entry_price=0.65,
            contracts=6,
            entry_time=time.time(),
            market_slug="test-market",
            min_price_seen=0.65,
            awaiting_resolution=True
        )

        self.assertTrue(position.awaiting_resolution)

        # Test _build_trade_record method directly
        record, pnl = TradingStats._build_trade_record(
            position,
            won=False,  # DOWN wins
            resolution_source="gamma_outcome",
            btc_anchor=50000.0,
            btc_current=50000.0
        )

        # Verify record
        self.assertIsNotNone(record)
        self.assertEqual(record.won, False)  # DOWN position wins
        self.assertEqual(record.resolution_source, "gamma_outcome")
        self.assertEqual(pnl, -3.50)  # Expected P&L


if __name__ == '__main__':
    unittest.main()