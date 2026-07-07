import unittest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from src.smart_scaling_engine import SmartScalingEngine, ScalingConfig, ScalingResult
from src.order_executor import OrderExecutor

class TestSmartScalingEngine(unittest.TestCase):
    """
    Tests for SmartScalingEngine
    """

    def setUp(self):
        # Create mock executor
        self.mock_executor = Mock(spec=OrderExecutor)
        self.mock_executor.simulation_mode = True
        self.mock_executor.get_order_book = AsyncMock()
        self.mock_executor.get_order_fills = AsyncMock()
        self.mock_executor._client = Mock()

        # Create scaling engine
        self.config = ScalingConfig(
            parts=5,
            total_duration_sec=10.0,
            initial_offset_usd=0.01,
            offset_increment_usd=0.005,
            max_spread_usd=0.05,
            taker_fallback_start=3
        )
        self.scaling_engine = SmartScalingEngine(
            executor=self.mock_executor,
            config=self.config
        )

    def test_calculate_maker_price_buy(self):
        """Test maker price calculation for buy orders"""
        best_bid = 0.50
        best_ask = 0.51

        # First slice
        price = self.scaling_engine.calculate_maker_price(
            "BUY", best_bid, best_ask, 0
        )
        # Should be limited to best_ask - buffer
        self.assertEqual(price, 0.509)  # best_ask - 0.001 buffer

        # Later slice with higher offset
        price = self.scaling_engine.calculate_maker_price(
            "BUY", best_bid, best_ask, 2
        )
        # Should still be limited to best_ask - buffer
        self.assertEqual(price, 0.509)  # best_ask - 0.001 buffer

        # With larger best_ask
        price = self.scaling_engine.calculate_maker_price(
            "BUY", best_bid, 0.60, 0  # Larger best_ask
        )
        # Should use calculated price
        expected = 0.50 + 0.01  # best_bid + initial_offset
        self.assertEqual(price, expected)

    def test_calculate_maker_price_sell(self):
        """Test maker price calculation for sell orders"""
        best_bid = 0.50
        best_ask = 0.51

        # First slice
        price = self.scaling_engine.calculate_maker_price(
            "SELL", best_bid, best_ask, 0
        )
        self.assertEqual(price, 0.501)  # best_bid + 0.001 buffer

        # Later slice with higher offset
        price = self.scaling_engine.calculate_maker_price(
            "SELL", best_bid, best_ask, 2
        )
        expected = 0.51 - 0.01 - (2 * 0.005)  # best_ask - initial - increment
        # 0.51 - 0.01 - 0.01 = 0.49, which is below best_bid + 0.001 (0.501)
        # So it should be capped at 0.501
        self.assertEqual(price, 0.501)

        # Don't drop below best_bid
        price = self.scaling_engine.calculate_maker_price(
            "SELL", 0.509, best_ask, 100  # Large offset
        )
        self.assertEqual(price, 0.509 + 0.001)  # best_bid + small buffer

    def test_check_spread(self):
        """Test spread checking"""
        # Within spread limit
        self.assertTrue(self.scaling_engine.check_spread(0.50, 0.54))  # 0.04 spread
        self.assertTrue(self.scaling_engine.check_spread(0.50, 0.549))  # 0.049 spread

        # Over spread limit
        self.assertFalse(self.scaling_engine.check_spread(0.50, 0.551))  # 0.051 spread
        self.assertFalse(self.scaling_engine.check_spread(0.50, 0.60))  # 0.10 spread

    @patch('random.random')
    def test_simulate_fill_probability_buy(self, mock_random):
        """Test fill probability simulation for buy orders"""
        mock_random.return_value = 0.5  # Always return 0.5

        # Close to best_ask - high probability
        prob = self.scaling_engine.simulate_fill_probability(
            "BUY", 0.509, 0.50, 0.51  # Very close to ask
        )
        self.assertGreater(prob, 0.8)

        # Far from best_ask - low probability
        prob = self.scaling_engine.simulate_fill_probability(
            "BUY", 0.440, 0.50, 0.51  # Far from ask
        )
        self.assertLess(prob, 0.4)

    @patch('random.random')
    def test_simulate_fill_probability_sell(self, mock_random):
        """Test fill probability simulation for sell orders"""
        mock_random.return_value = 0.5

        # Close to best_bid - high probability
        prob = self.scaling_engine.simulate_fill_probability(
            "SELL", 0.501, 0.50, 0.51  # Very close to bid
        )
        self.assertGreater(prob, 0.8)

        # Far from best_bid - low probability
        prob = self.scaling_engine.simulate_fill_probability(
            "SELL", 0.560, 0.50, 0.51  # Far from bid
        )
        self.assertLess(prob, 0.4)

    @patch('random.random')
    def test_simulate_fill(self, mock_random):
        """Test fill simulation"""
        # High probability - full fill
        mock_random.side_effect = [0.5, 0.5]
        filled = self.scaling_engine.simulate_fill("BUY", 10, 0.9)
        self.assertEqual(filled, 10)

        # Low probability - no fill
        mock_random.side_effect = [0.5]
        filled = self.scaling_engine.simulate_fill("BUY", 10, 0.2)
        self.assertEqual(filled, 0)

        # Medium probability - partial fill
        mock_random.side_effect = [0.3, 0.8]  # First: fill check (0.3 < 0.5 -> True), Second: partial check (0.8 < 0.7 -> False)
        filled = self.scaling_engine.simulate_fill("BUY", 10, 0.5)
        self.assertEqual(filled, 5)  # Half fill

    async def test_scale_in_simulation_mode(self):
        """Test scaling in simulation mode"""
        # Mock order book data
        self.mock_executor.get_order_book.return_value = {
            "best_bid": 0.50,
            "best_ask": 0.51
        }

        # Run scaling
        result = await self.scaling_engine.scale_in(
            token_id="test123",
            total_budget=10.0,
            side="BUY"
        )

        self.assertIsInstance(result, ScalingResult)
        self.assertTrue(result.success)
        self.assertGreater(result.contracts_filled, 0)
        self.assertGreater(result.total_cost, 0)
        self.assertEqual(result.slices_executed, 5)
        self.assertEqual(result.taker_fills, 0)  # All maker in simulation

    async def test_scale_in_simulation_taker_fallback(self):
        """Test scaling with taker fallback"""
        # Mock order book data
        self.mock_executor.get_order_book.return_value = {
            "best_bid": 0.50,
            "best_ask": 0.51
        }

        # Run scaling with more slices
        result = await self.scaling_engine.scale_in(
            token_id="test123",
            total_budget=20.0,
            side="BUY"
        )

        self.assertIsInstance(result, ScalingResult)
        self.assertTrue(result.success)
        self.assertGreater(result.contracts_filled, 0)

    async def test_scale_in_wide_spread(self):
        """Test scaling with wide spread"""
        # Mock wide spread
        self.mock_executor.get_order_book.return_value = {
            "best_bid": 0.50,
            "best_ask": 0.60  # Wide spread
        }

        # Run scaling
        result = await self.scaling_engine.scale_in(
            token_id="test123",
            total_budget=10.0,
            side="BUY"
        )

        # Should succeed but with fewer fills due to wide spread
        self.assertIsInstance(result, ScalingResult)

    async def test_scale_in_real_mode(self):
        """Test scaling in real mode"""
        self.mock_executor.simulation_mode = False

        # Mock order book
        self.mock_executor.get_order_book.return_value = {
            "best_bid": 0.50,
            "best_ask": 0.51
        }

        # Mock order creation and execution
        self.mock_executor._client.create_order.return_value = {"id": "order123"}
        self.mock_executor._client.post_order.return_value = {"success": True}
        self.mock_executor._client.cancel_order.return_value = {"success": True}
        self.mock_executor.get_order_fills.return_value = 5

        # Run scaling
        result = await self.scaling_engine.scale_in(
            token_id="test123",
            total_budget=10.0,
            side="BUY"
        )

        self.assertIsInstance(result, ScalingResult)
        self.assertTrue(result.success)
        self.assertGreater(result.contracts_filled, 0)

if __name__ == '__main__':
    unittest.main()