#!/usr/bin/env python3
"""
Demo script for Dual-Side Scaling Strategy
Shows how all components work together
"""

import asyncio
import time
import random
from typing import Dict, List
from src.dual_side_scaling_manager import DualSideScalingManager, DualSideConfig
from src.market_regime_analyzer import MarketRegimeAnalyzer
from src.smart_scaling_engine import SmartScalingEngine, ScalingConfig
from src.deferred_resolution_manager import DeferredResolutionManager
from src.order_executor import OrderExecutor

class MockOrderExecutor(OrderExecutor):
    """Mock order executor for demo"""

    def __init__(self):
        self.simulation_mode = True
        self.initial_balance = 100.0
        self.token_prices = {
            "up": 0.55,
            "down": 0.45
        }

    def get_token_price(self, token_id: str) -> float:
        return self.token_prices.get(token_id, 0.5)

    def get_order_book(self, token_id: str):
        return {
            "best_bid": self.get_token_price(token_id) - 0.01,
            "best_ask": self.get_token_price(token_id) + 0.01,
            "bids": [{"price": str(self.get_token_price(token_id) - 0.01), "size": "100"}],
            "asks": [{"price": str(self.get_token_price(token_id) + 0.01), "size": "100"}]
        }

    async def get_order_book_async(self, token_id: str):
        return self.get_order_book(token_id)

def generate_market_data() -> Dict:
    """Generate realistic market data for demo"""
    base_price = 0.50
    # Simulate price movement
    price_change = random.uniform(-0.02, 0.02)
    up_price = max(0.1, min(0.9, base_price + price_change))
    down_price = 1.0 - up_price  # Ensure sum = 1.0

    # Generate order book
    spread = random.uniform(0.01, 0.03)
    return {
        "up_token": {
            "price": up_price,
            "bid": up_price - spread/2,
            "ask": up_price + spread/2,
            "volume": random.randint(100, 1000)
        },
        "down_token": {
            "price": down_price,
            "bid": down_price - spread/2,
            "ask": down_price + spread/2,
            "volume": random.randint(100, 1000)
        },
        "btc_price": random.uniform(50000, 60000),
        "time": time.time()
    }

async def demo_regime_detection():
    """Demo regime detection component"""
    print("=" * 60)
    print("Demo: Regime Detection")
    print("=" * 60)

    # Create analyzer
    analyzer = MarketRegimeAnalyzer(
        price_window=20,
        ofi_window=5
    )

    # Simulate trending market
    print("Simulating TRENDING market...")
    trending_prices = [0.50 + i * 0.001 for i in range(20)]  # Slow upward trend
    for price in trending_prices:
        analyzer.update_price(price)

    # Add order book showing upward pressure
    analyzer.update_order_book(
        bids=[{"price": "0.50", "size": "200"}],
        asks=[{"price": "0.51", "size": "100"}]
    )

    regime_info = analyzer.analyze_regime(recent_move_pct=2.0)
    print(f"Regime: {regime_info.regime}")
    print(f"Dominant side: {regime_info.dominant_side}")
    print(f"Hurst exponent: {regime_info.hurst:.3f}")
    print(f"OFI: {regime_info.ofi}")

    # Show confidence
    summary = analyzer.get_regime_summary()
    print(f"Confidence: {summary['confidence']:.2f}")
    print()

async def demo_kelly_calculation():
    """Demo Kelly calculation"""
    print("=" * 60)
    print("Demo: Kelly Criterion Calculation")
    print("=" * 60)

    from src.regime_strategy import KellyCriterionCalculator

    scenarios = [
        {"win_prob": 0.60, "price": 0.50, "desc": "Good edge"},
        {"win_prob": 0.55, "price": 0.50, "desc": "Small edge"},
        {"win_prob": 0.52, "price": 0.52, "desc": "Break-even"},
        {"win_prob": 0.50, "price": 0.55, "desc": "Negative edge"},
    ]

    for scenario in scenarios:
        standard = KellyCriterionCalculator.calculate(
            scenario["win_prob"],
            scenario["price"]
        )

        conservative = KellyCriterionCalculator.calculate_conservative(
            scenario["win_prob"],
            scenario["price"]
        )

        budget = 20.0
        allocated_standard = standard * budget
        allocated_conservative = conservative * budget

        print(f"Scenario: {scenario['desc']}")
        print(f"  Win Prob: {scenario['win_prob']:.1%}, Price: ${scenario['price']:.2f}")
        print(f"  Standard Kelly: {standard:.4f} (${allocated_standard:.2f})")
        print(f"  Conservative Kelly: {conservative:.4f} (${allocated_conservative:.2f})")
        print(f"  Recommendation: {'PROCEED' if max(allocated_standard, allocated_conservative) > 1.0 else 'SKIP'}")
        print()

async def demo_scaling_engine():
    """Demo smart scaling engine"""
    print("=" * 60)
    print("Demo: Smart Scaling Engine")
    print("=" * 60)

    # Create mock executor
    mock_executor = MockOrderExecutor()

    # Create scaling engine
    scaling_config = ScalingConfig(
        parts=5,
        total_duration_sec=10.0,
        initial_offset_usd=0.01,
        offset_increment_usd=0.005,
        max_spread_usd=0.05
    )

    scaling_engine = SmartScalingEngine(mock_executor, scaling_config)

    print("Running scaling simulation...")
    print("Token ID: up, Budget: $10.00")

    # Mock the order book calls
    mock_executor.get_order_book = lambda token: mock_executor.get_order_book(token)

    result = await scaling_engine.scale_in(
        token_id="up",
        total_budget=10.0,
        side="BUY"
    )

    print(f"Success: {result.success}")
    print(f"Contracts filled: {result.contracts_filled}")
    print(f"Average price: ${result.avg_price:.4f}")
    print(f"Total cost: ${result.total_cost:.2f}")
    print(f"Maker fills: {result.maker_fills}")
    print(f"Taker fills: {result.taker_fills}")
    print()

async def demo_deferred_resolution():
    """Demo deferred resolution management"""
    print("=" * 60)
    print("Demo: Deferred Resolution Manager")
    print("=" * 60)

    # Create manager
    manager = DeferredResolutionManager(
        max_pending=5,
        resolution_interval_sec=30,
        max_wait_minutes=2
    )

    # Add pending resolution
    position_data = {
        "contracts": 10,
        "entry_price": 0.60,
        "token_name": "UP",
        "btc_anchor_price": 50000,
        "btc_current_price": 51000
    }

    manager.add_pending_resolution(
        market_slug="btc-updown-5m-1234567890",
        condition_id="cond-123",
        end_time=time.time() + 60,
        position_data=position_data
    )

    print("Added pending resolution:")
    print(f"  Market: btc-updown-5m-1234567890")
    print(f"  End time: {time.ctime(time.time() + 60)}")
    print(f"  Position: 10 contracts at $0.60")

    # Show summary
    print("\nSummary:")
    print(f"  Pending count: {manager.get_pending_count()}")
    print(f"  Next expiration: {time.ctime(manager.get_next_expiration())}")

    # Create trade record
    from src.deferred_resolution_manager import ResolutionResult
    resolution = ResolutionResult(
        market_slug="btc-updown-5m-1234567890",
        condition_id="cond-123",
        won=True,
        outcome="UP",
        resolution_price=1.0,
        timestamp=time.time(),
        source="gamma_api"
    )

    record = manager.create_trade_record(manager.pending_resolutions[0], resolution)
    print(f"\nTrade record created:")
    print(f"  Market: {record['market_slug']}")
    print(f"  Won: {record['won']}")
    print(f"  P&L: ${record['pnl']:.2f}")
    print(f"  Trade number: {record['trade_number']}")
    print()

async def demo_full_integration():
    """Demo full integration of all components"""
    print("=" * 60)
    print("Demo: Full Integration - Dual-Side Scaling")
    print("=" * 60)

    # Create mock executor
    mock_executor = MockOrderExecutor()

    # Create dual-side manager
    config = DualSideConfig(
        scaling_parts=5,
        scaling_duration_sec=10.0,
        use_conservative_kelly=True,
        max_daily_trades=100
    )

    manager = DualSideScalingManager(mock_executor, config)

    # Simulate market data
    print("Simulating market data...")
    market_data = generate_market_data()

    # Update regime analyzer
    manager.update_price_data(market_data["up_token"]["price"])
    manager.update_order_book_data(
        bids=market_data["up_token"]["bids"],
        asks=market_data["up_token"]["asks"]
    )

    # Analyze regime
    regime_info = manager.analyze_regime()
    print(f"Current regime: {regime_info.regime}")
    print(f"Dominant side: {regime_info.dominant_side}")

    # Calculate trade decision
    decision = manager.calculate_trade_decision(
        win_prob=0.58,
        token_price=market_data["up_token"]["price"]
    )

    if decision:
        print("\nTrade decision:")
        print(f"  Kelly fraction: {decision.kelly_fraction:.4f}")
        print(f"  Total budget: ${decision.total_budget:.2f}")
        print(f"  Dominant: ${decision.dominant_budget:.2f} ({decision.dominant_side})")
        print(f"  Insurance: ${decision.insurance_budget:.2f} ({decision.insurance_side})")
        print(f"  Confidence: {decision.confidence:.2f}")

        # Execute trade
        print("\nExecuting dual-side trade...")
        success, result = await manager.execute_dual_side_trade(
            up_token_id="up_token",
            down_token_id="down_token",
            win_prob=0.58
        )

        print(f"Trade executed: {success}")
        if success:
            print(f"  Dominant success: {result['dominant_success']}")
            print(f"  Insurance success: {result['insurance_success']}")

        # Record outcome
        manager.record_trade_outcome(
            won=True,
            pnl=2.50,
            regime=decision.regime_info.regime,
            confidence=decision.confidence
        )

        # Show summary
        summary = manager.get_summary()
        print(f"\nSummary:")
        print(f"  Daily trades: {summary['daily_trades']}")
        print(f"  Daily P&L: ${summary['daily_pnl']:.2f}")
        print(f"  Consecutive losses: {summary['consecutive_losses']}")
    else:
        print("No trade decision made")

    print()

async def main():
    """Main demo function"""
    print("Dual-Side Scaling Strategy Demo")
    print("=" * 80)

    await demo_regime_detection()
    await demo_kelly_calculation()
    await demo_scaling_engine()
    await demo_deferred_resolution()
    await demo_full_integration()

    print("Demo completed!")

if __name__ == "__main__":
    asyncio.run(main())