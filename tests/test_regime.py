import unittest
import numpy as np
from src.regime_strategy import (
    HurstExponentCalculator,
    OrderFlowImbalanceCalculator,
    KellyCriterionCalculator,
    RegimeDetector
)

class TestRegimeStrategy(unittest.TestCase):
    """
    Tests for the Regime Strategy calculators.
    """
    def test_hurst_trending(self):
        # Generate a highly trending price series (persistent)
        # Price going steadily up with tiny noise
        prices = [100.0 + i + np.random.normal(0, 0.05) for i in range(100)]
        H = HurstExponentCalculator.calculate(prices)
        # Trending series should have H > 0.5
        self.assertGreater(H, 0.5)
        
    def test_hurst_mean_reverting(self):
        # Generate a mean-reverting series (anti-persistent)
        # e.g., prices alternating or oscillating around a mean
        prices = [100.0 + (i % 2) * 2.0 + np.random.normal(0, 0.05) for i in range(100)]
        H = HurstExponentCalculator.calculate(prices)
        # Mean reverting series should have H < 0.5
        self.assertLess(H, 0.5)

    def test_ofi_calculator(self):
        ofi_calc = OrderFlowImbalanceCalculator()
        
        # Initial update returns 0.0
        val = ofi_calc.update(bid_price=10.0, bid_size=100, ask_price=10.1, ask_size=100)
        self.assertEqual(val, 0.0)
        
        # Price goes up, bid size is positive
        val = ofi_calc.update(bid_price=10.1, bid_size=120, ask_price=10.2, ask_size=90)
        # Delta Bid = 120 (since bid_price > last_bid_price)
        # Delta Ask = 0 (since ask_price > last_ask_price)
        # OFI = 120 - 0 = 120
        self.assertEqual(val, 120.0)
        
        # Price is equal, bid size increases, ask size increases
        val = ofi_calc.update(bid_price=10.1, bid_size=150, ask_price=10.2, ask_size=100)
        # Delta Bid = 150 - 120 = 30
        # Delta Ask = 100 - 90 = 10
        # OFI = 30 - 10 = 20
        self.assertEqual(val, 20.0)
        
        # Price goes down
        val = ofi_calc.update(bid_price=10.0, bid_size=100, ask_price=10.1, ask_size=110)
        # Delta Bid = 0 (since bid_price < last_bid_price)
        # Delta Ask = 110 (since ask_price < last_ask_price)
        # OFI = 0 - 110 = -110
        self.assertEqual(val, -110.0)

    def test_ofi_multi_level(self):
        ofi_calc = OrderFlowImbalanceCalculator()
        
        # Initial update
        bids1 = [{"price": "10.0", "size": "100"}, {"price": "9.9", "size": "200"}]
        asks1 = [{"price": "10.1", "size": "100"}, {"price": "10.2", "size": "200"}]
        val = ofi_calc.update_multi_level(bids1, asks1)
        self.assertEqual(val, 0.0)
        
        # Price increases
        bids2 = [{"price": "10.1", "size": "150"}, {"price": "10.0", "size": "100"}]
        asks2 = [{"price": "10.2", "size": "250"}, {"price": "10.3", "size": "200"}]
        val = ofi_calc.update_multi_level(bids2, asks2)
        # best_bid_price increases (10.0 -> 10.1), so Delta Bid = sum of sizes = 150 + 100 = 250
        # best_ask_price increases (10.1 -> 10.2), so Delta Ask = 0
        # OFI = 250 - 0 = 250
        self.assertEqual(val, 250.0)

    def test_kelly_calculator(self):
        # win_prob = 0.6, price = 0.5 (even odds)
        # f* = (0.6 - 0.5) / (0.5 * 0.5) = 0.1 / 0.25 = 0.4
        # Half-Kelly = 0.2
        fraction = KellyCriterionCalculator.calculate(win_prob=0.6, price=0.5, half_kelly=True)
        self.assertAlmostEqual(fraction, 0.2)
        
        # Full Kelly
        fraction_full = KellyCriterionCalculator.calculate(win_prob=0.6, price=0.5, half_kelly=False)
        self.assertAlmostEqual(fraction_full, 0.4)
        
        # win_prob < price -> should return 0.0
        fraction_zero = KellyCriterionCalculator.calculate(win_prob=0.4, price=0.5)
        self.assertEqual(fraction_zero, 0.0)

    def test_regime_detector(self):
        self.assertEqual(RegimeDetector.detect(0.6, 100.0), "TRENDING")
        self.assertEqual(RegimeDetector.detect(0.4, -100.0), "MEAN_REVERTING")
        self.assertEqual(RegimeDetector.detect(0.5, 0.0), "NEUTRAL")

if __name__ == '__main__':
    unittest.main()
