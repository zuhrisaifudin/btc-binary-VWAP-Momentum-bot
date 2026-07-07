#!/usr/bin/env python3
"""
Simple demo of dual-side scaling strategy
"""

from src.regime_strategy import KellyCriterionCalculator
from src.market_regime_analyzer import MarketRegimeAnalyzer

def demo_kelly():
    print("Kelly Criterion Demo")
    print("-" * 40)

    scenarios = [
        (0.60, 0.50, "Good edge"),
        (0.55, 0.50, "Small edge"),
        (0.52, 0.52, "Break-even"),
        (0.50, 0.55, "Negative edge"),
    ]

    for win_prob, price, desc in scenarios:
        standard = KellyCriterionCalculator.calculate(win_prob, price)
        conservative = KellyCriterionCalculator.calculate_conservative(win_prob, price)

        budget = 20.0
        allocated_standard = standard * budget
        allocated_conservative = conservative * budget

        print(f"{desc}:")
        print(f"  Win Prob: {win_prob:.1%}, Price: ${price:.2f}")
        print(f"  Standard: ${allocated_standard:.2f} ({standard:.3f})")
        print(f"  Conservative: ${allocated_conservative:.2f} ({conservative:.3f})")
        print()

def demo_regime():
    print("Regime Detection Demo")
    print("-" * 40)

    # Create analyzer
    analyzer = MarketRegimeAnalyzer()

    # Add trending data
    for i in range(20):
        analyzer.update_price(0.50 + i * 0.001)

    # Add OFI data
    analyzer.update_order_book(
        bids=[{"price": "0.50", "size": "200"}],
        asks=[{"price": "0.51", "size": "100"}]
    )

    # Analyze
    regime_info = analyzer.analyze_regime(recent_move_pct=2.0)
    summary = analyzer.get_regime_summary()

    print(f"Regime: {regime_info.regime}")
    print(f"Dominant side: {regime_info.dominant_side}")
    print(f"Hurst: {regime_info.hurst:.3f}")
    print(f"Confidence: {summary['confidence']:.2f}")
    print()

def main():
    print("Dual-Side Scaling Strategy - Simple Demo")
    print("=" * 50)
    print()

    demo_kelly()
    demo_regime()

    print("Integration ready!")
    print("Next steps:")
    print("1. Configure config.json with dual-side settings")
    print("2. Update main.py to use DualSideScalingManager")
    print("3. Test in simulation mode first")
    print("4. Monitor performance and adjust parameters")

if __name__ == "__main__":
    main()