import unittest
import numpy as np
from unittest.mock import Mock, patch
from src.market_regime_analyzer import MarketRegimeAnalyzer, MarketRegimeInfo

class TestMarketRegimeAnalyzer(unittest.TestCase):
    """
    Tests for MarketRegimeAnalyzer
    """

    def setUp(self):
        self.analyzer = MarketRegimeAnalyzer(
            price_window=20,
            ofi_window=5,
            min_price_threshold=0.30,
            max_price_threshold=0.70
        )

    def test_analyze_neutral_regime_insufficient_data(self):
        """Test neutral regime with insufficient data"""
        # Empty price history
        regime_info = self.analyzer.analyze_regime()

        self.assertEqual(regime_info.regime, "NEUTRAL")
        self.assertIsNone(regime_info.dominant_side)
        self.assertEqual(regime_info.hurst, 0.5)

    @patch('src.market_regime_analyzer.HurstExponentCalculator.calculate')
    def test_analyze_trending_regime(self, mock_hurst):
        """Test trending regime detection"""
        # Add price history
        prices = [0.5 + i * 0.01 for i in range(10)]  # Valid price range
        for price in prices:
            self.analyzer.update_price(price)

        # Add order book data to set OFI
        self.analyzer.update_order_book(
            bids=[{"price": "0.50", "size": "100"}],
            asks=[{"price": "0.51", "size": "100"}]
        )

        # Mock Hurst exponent
        mock_hurst.return_value = 0.60  # Trending

        # Also mock get_recent_move_pct
        with patch.object(self.analyzer, 'get_recent_move_pct', return_value=1.0):
            regime_info = self.analyzer.analyze_regime()

        self.assertEqual(regime_info.regime, "TRENDING")
        # Should follow OFI direction
        self.assertIn(regime_info.dominant_side, ["UP", "DOWN"])

    @patch('src.market_regime_analyzer.HurstExponentCalculator.calculate')
    def test_analyze_mean_reverting_regime(self, mock_hurst):
        """Test mean reverting regime detection"""
        # Add price history
        prices = [100.0, 101.0, 99.0, 102.0, 98.0]  # Oscillating
        for price in prices:
            self.analyzer.update_price(price)

        # Mock Hurst exponent
        mock_hurst.return_value = 0.30  # Mean reverting

        regime_info = self.analyzer.analyze_regime()

        self.assertEqual(regime_info.regime, "MEAN_REVERTING")
        # Should bet against recent move
        if regime_info.recent_move_pct > 0:
            self.assertEqual(regime_info.dominant_side, "DOWN")
        elif regime_info.recent_move_pct < 0:
            self.assertEqual(regime_info.dominant_side, "UP")

    def test_get_kelly_allocation_conservative(self):
        """Test Kelly allocation with conservative method"""
        # Set up regime
        self.analyzer.regime_info = MarketRegimeInfo(
            regime="TRENDING",
            dominant_side="UP",
            hurst=0.60,
            ofi=10.0,
            ofi_ma=8.0,
            recent_move_pct=2.0,
            timestamp=1234567890
        )

        # Test conservative Kelly
        kelly_frac, side = self.analyzer.get_kelly_allocation(
            win_prob=0.65,
            token_price=0.55,
            use_conservative=True
        )

        self.assertGreater(kelly_frac, 0)
        self.assertEqual(side, "UP")

    def test_get_kelly_allocation_no_positive_edge(self):
        """Test Kelly allocation with no positive edge"""
        # Set up regime
        self.analyzer.regime_info = MarketRegimeInfo(
            regime="TRENDING",
            dominant_side="UP",
            hurst=0.60,
            ofi=10.0,
            ofi_ma=8.0,
            recent_move_pct=2.0,
            timestamp=1234567890
        )

        # Test with win_prob < price (no positive edge)
        kelly_frac, side = self.analyzer.get_kelly_allocation(
            win_prob=0.50,
            token_price=0.55
        )

        self.assertEqual(kelly_frac, 0.0)
        # Side should still be available for position tracking, even with no Kelly
        self.assertEqual(side, "UP")

    def test_should_trade_with_valid_regime(self):
        """Test should_trade with valid regime"""
        # Set up regime
        self.analyzer.regime_info = MarketRegimeInfo(
            regime="TRENDING",
            dominant_side="UP",
            hurst=0.60,
            ofi=10.0,
            ofi_ma=8.0,
            recent_move_pct=2.0,
            timestamp=1234567890
        )

        should_trade, side = self.analyzer.should_trade(token_price=0.50)

        self.assertTrue(should_trade)
        self.assertEqual(side, "UP")

    def test_should_trade_price_out_of_range(self):
        """Test should_trade with price out of range"""
        # Set up regime
        self.analyzer.regime_info = MarketRegimeInfo(
            regime="TRENDING",
            dominant_side="UP",
            hurst=0.60,
            ofi=10.0,
            ofi_ma=8.0,
            recent_move_pct=2.0,
            timestamp=1234567890
        )

        # Price above max threshold
        should_trade, side = self.analyzer.should_trade(token_price=0.80)

        self.assertFalse(should_trade)
        self.assertIsNone(side)

    def test_should_trade_neutral_regime(self):
        """Test should_trade with neutral regime"""
        # Set up regime
        self.analyzer.regime_info = MarketRegimeInfo(
            regime="NEUTRAL",
            dominant_side=None,
            hurst=0.50,
            ofi=0.0,
            ofi_ma=0.0,
            recent_move_pct=0.0,
            timestamp=1234567890
        )

        should_trade, side = self.analyzer.should_trade(token_price=0.50)

        self.assertFalse(should_trade)
        self.assertIsNone(side)

    def test_get_regime_summary(self):
        """Test regime summary"""
        # Set up regime
        self.analyzer.regime_info = MarketRegimeInfo(
            regime="TRENDING",
            dominant_side="UP",
            hurst=0.60,
            ofi=10.0,
            ofi_ma=8.0,
            recent_move_pct=2.0,
            timestamp=1234567890
        )

        summary = self.analyzer.get_regime_summary()

        self.assertEqual(summary["regime"], "TRENDING")
        self.assertEqual(summary["dominant_side"], "UP")
        self.assertEqual(summary["hurst"], 0.60)
        self.assertEqual(summary["ofi"], 10.0)
        self.assertEqual(summary["ofi_ma"], 8.0)
        self.assertEqual(summary["recent_move_pct"], 2.0)
        self.assertTrue(summary["should_trade"])
        self.assertEqual(summary["recommendation"], "UP")
        self.assertGreater(summary["confidence"], 0)

if __name__ == '__main__':
    unittest.main()