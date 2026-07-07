import unittest
import asyncio
import json
import tempfile
import os
from unittest.mock import Mock, AsyncMock, patch
from src.deferred_resolution_manager import (
    DeferredResolutionManager,
    PendingResolution,
    ResolutionResult
)

class TestDeferredResolutionManager(unittest.TestCase):
    """
    Tests for DeferredResolutionManager
    """

    def setUp(self):
        self.manager = DeferredResolutionManager(
            max_pending=10,
            resolution_interval_sec=30,
            max_wait_minutes=120
        )

        # Mock gamma API client
        self.mock_gamma_client = Mock()
        self.mock_gamma_client.get = AsyncMock()

    def test_add_pending_resolution(self):
        """Test adding pending resolution"""
        # Add pending resolution
        position_data = {
            "contracts": 10,
            "entry_price": 0.60,
            "token_name": "UP",
            "hedged": False
        }

        self.manager.add_pending_resolution(
            market_slug="test-market-123",
            condition_id="cond-456",
            end_time=1234567890,
            position_data=position_data
        )

        # Check it was added
        self.assertEqual(len(self.manager.pending_resolutions), 1)
        self.assertEqual(self.manager.pending_resolutions[0].market_slug, "test-market-123")
        self.assertIn("test-market-123", self.manager.markets_seen)

    def test_add_duplicate_market(self):
        """Test adding duplicate market"""
        position_data = {"contracts": 10, "entry_price": 0.60}

        # Add first time
        self.manager.add_pending_resolution(
            "test-market", "cond1", 1234567890, position_data
        )
        self.assertEqual(len(self.manager.pending_resolutions), 1)

        # Add second time (should be ignored)
        self.manager.add_pending_resolution(
            "test-market", "cond2", 1234567890, position_data
        )
        self.assertEqual(len(self.manager.pending_resolutions), 1)  # No duplicate

    @patch('src.deferred_resolution_manager.time.time')
    async def test_resolve_via_gamma_success(self, mock_time):
        """Test successful resolution via Gamma API"""
        mock_time.return_value = 1234567890  # Current time

        # Add pending resolution
        position_data = {
            "contracts": 10,
            "entry_price": 0.60,
            "token_name": "UP"
        }
        self.manager.add_pending_resolution(
            "test-market", "cond1", 1230000000, position_data
        )

        # Mock successful gamma API response
        gamma_response = {
            "data": {
                "closed": True,
                "outcomePrices": [0.80, 0.20]  # UP wins
            }
        }
        self.mock_gamma_client.get.return_value = gamma_response

        # Resolve
        results = await self.manager.resolve_pending_markets(self.mock_gamma_client)

        # Check result
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertTrue(result.won)
        self.assertEqual(result.outcome, "UP")
        self.assertEqual(result.source, "gamma_api")

        # Check it's marked as resolved
        self.assertIsNotNone(self.manager.pending_resolutions[0].resolved_at)

    @patch('src.deferred_resolution_manager.time.time')
    async def test_resolve_via_gamma_not_closed(self, mock_time):
        """Test market not closed yet"""
        mock_time.return_value = 1234567890

        position_data = {"contracts": 10, "entry_price": 0.60}
        self.manager.add_pending_resolution(
            "test-market", "cond1", 1230000000, position_data
        )

        # Mock market not closed
        gamma_response = {
            "data": {
                "closed": False,
                "outcomePrices": [0.80, 0.20]
            }
        }
        self.mock_gamma_client.get.return_value = gamma_response

        # Resolve (should not resolve)
        results = await self.manager.resolve_pending_markets(self.mock_gamma_client)

        self.assertEqual(len(results), 0)  # Not resolved yet

    @patch('src.deferred_resolution_manager.time.time')
    async def test_fallback_resolution_chainlink(self, mock_time):
        """Test fallback resolution with Chainlink"""
        mock_time.return_value = 1234567890

        position_data = {
            "contracts": 10,
            "entry_price": 0.60,
            "token_name": "UP",
            "btc_anchor_price": 50000,
            "btc_current_price": 51000  # BTC went up
        }
        self.manager.add_pending_resolution(
            "test-market", "cond1", 1230000000, position_data
        )

        # Mock gamma API failure
        self.mock_gamma_client.get.side_effect = Exception("API Error")

        # Resolve
        results = await self.manager.resolve_pending_markets(self.mock_gamma_client)

        # Check result
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertTrue(result.won)  # UP wins when BTC goes up
        self.assertEqual(result.outcome, "UP")
        self.assertEqual(result.source, "chainlink_oracle")

    def test_determine_winner(self):
        """Test winner determination"""
        position_data = {"token_name": "UP"}

        # UP wins
        result = self.manager._determine_winner([0.80, 0.20], position_data)
        self.assertTrue(result[0])  # won
        self.assertEqual(result[1], "UP")

        # DOWN wins
        result = self.manager._determine_winner([0.20, 0.80], position_data)
        self.assertFalse(result[0])  # won
        self.assertEqual(result[1], "DOWN")

    def test_determine_via_chainlink(self):
        """Test Chainlink determination"""
        position_data = {"token_name": "UP"}

        # BTC goes up
        won, outcome = self.manager._determine_via_chainlink(
            50000, 51000, position_data
        )
        self.assertTrue(won)  # UP wins
        self.assertEqual(outcome, "UP")

        # BTC goes down
        won, outcome = self.manager._determine_via_chainlink(
            50000, 49000, position_data
        )
        self.assertFalse(won)  # UP loses
        self.assertEqual(outcome, "DOWN")

    def test_get_pending_count(self):
        """Test getting pending count"""
        self.assertEqual(self.manager.get_pending_count(), 0)

        # Add pending
        position_data = {"contracts": 10}
        self.manager.add_pending_resolution("test1", "cond1", 1234567890, position_data)
        self.assertEqual(self.manager.get_pending_count(), 1)

    def test_get_next_expiration(self):
        """Test getting next expiration"""
        # No pending
        self.assertIsNone(self.manager.get_next_expiration())

        # Add pending
        position_data = {"contracts": 10}
        self.manager.add_pending_resolution("test1", "cond1", 1234567890, position_data)
        self.assertEqual(self.manager.get_next_expiration(), 1234567890)

    def test_save_and_load_pending(self):
        """Test saving and loading pending resolutions"""
        # Add pending
        position_data = {"contracts": 10, "entry_price": 0.60}
        self.manager.add_pending_resolution("test1", "cond1", 1234567890, position_data)
        self.manager.trade_number = 5

        # Create temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_file = f.name

        try:
            # Save
            self.manager.save_pending_to_file(temp_file)

            # Create new manager and load
            new_manager = DeferredResolutionManager()
            new_manager.load_pending_from_file(temp_file)

            # Check data
            self.assertEqual(len(new_manager.pending_resolutions), 1)
            self.assertEqual(new_manager.pending_resolutions[0].market_slug, "test1")
            self.assertEqual(new_manager.trade_number, 5)

        finally:
            # Clean up
            os.unlink(temp_file)

    def test_create_trade_record(self):
        """Test creating trade record"""
        pending = PendingResolution(
            market_slug="test-market",
            condition_id="cond1",
            end_time=1234567890,
            position_data={
                "contracts": 10,
                "entry_price": 0.60,
                "token_name": "UP",
                "hedged": False,
                "min_price_seen": 0.55
            },
            created_at=1234567890
        )

        resolution = ResolutionResult(
            market_slug="test-market",
            condition_id="cond1",
            won=True,
            outcome="UP",
            resolution_price=1.0,
            timestamp=1234567890,
            source="gamma_api"
        )

        record = self.manager.create_trade_record(pending, resolution)

        # Check record
        self.assertEqual(record["market_slug"], "test-market")
        self.assertEqual(record["token_name"], "UP")
        self.assertEqual(record["entry_price"], 0.60)
        self.assertEqual(record["exit_price"], 1.0)
        self.assertEqual(record["contracts"], 10)
        self.assertEqual(record["won"], True)
        self.assertEqual(record["pnl"], 4.0)  # (10 - 6.0) = 4.0
        self.assertEqual(record["trade_number"], 0)  # Starts at 0

        # Check trade number incremented
        self.assertEqual(self.manager.trade_number, 1)

if __name__ == '__main__':
    unittest.main()