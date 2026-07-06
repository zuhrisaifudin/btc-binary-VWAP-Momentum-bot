#!/usr/bin/env python3
"""
Test suite for order sizing validation.

Tests contract calculations, minimum order checks, and validation logic.
"""

import unittest
from unittest.mock import patch

from src.order_executor import OrderExecutor, ExecutionConfig, MIN_ORDER_USD


class TestOrderSizing(unittest.TestCase):
    """Test order sizing calculations and validation."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock credentials for testing
        self.executor = OrderExecutor(
            private_key="0x123",
            api_key="test_key",
            api_secret="test_secret",
            api_passphrase="test_pass",
            clob_host="test.com",
            chain_id=137,
            signature_type="eth_personal_sign",
            funder_address=None,
            user_ws=None,
            simulation_mode=True
        )

    def test_calculate_contracts_normal(self):
        """Test normal contract calculation."""
        # $1.00 budget at $0.50 price = 2 contracts
        contracts = self.executor._calculate_contracts(1.00, 0.50)
        self.assertEqual(contracts, 2)

        # $1.50 budget at $0.75 price = 2 contracts (floor division)
        contracts = self.executor._calculate_contracts(1.50, 0.75)
        self.assertEqual(contracts, 2)

    def test_calculate_contracts_minimum(self):
        """Test minimum contract enforcement."""
        # Very small budget - should return MIN_CONTRACTS
        contracts = self.executor._calculate_contracts(0.01, 0.99)
        self.assertEqual(contracts, 1)  # MIN_CONTRACTS

        # Zero price - should return MIN_CONTRACTS
        contracts = self.executor._calculate_contracts(1.00, 0.00)
        self.assertEqual(contracts, 1)

    def test_validate_order_size_normal(self):
        """Test normal order size validation."""
        contracts, is_valid = self.executor._validate_order_size(10, 0.10)
        self.assertEqual(contracts, 10)
        self.assertTrue(is_valid)

        # Test minimum contracts
        contracts, is_valid = self.executor._validate_order_size(0, 0.10)
        self.assertEqual(contracts, 1)  # MIN_CONTRACTS
        self.assertTrue(is_valid)

    def test_validate_order_size_minimum_order(self):
        """Test minimum order size validation."""
        # Test order below minimum - should be adjusted
        contracts, is_valid = self.executor._validate_order_size(1, 0.005)  # $0.005 < $0.01
        self.assertGreater(contracts, 1)
        self.assertTrue(is_valid)

        # Test exact minimum order
        contracts, is_valid = self.executor._validate_order_size(1, 0.01)  # Exactly $0.01
        self.assertEqual(contracts, 1)
        self.assertTrue(is_valid)

    @patch.object(OrderExecutor, 'get_best_ask')
    async def test_execute_dual_position_trap_too_small(self, mock_get_ask):
        """Test dual execution with trap below minimum."""
        mock_get_ask.return_value = 0.20  # Both tokens at $0.20

        # Very small total budget that makes trap too small
        # Total: $0.10, Trap allocation: 15% = $0.015 < $0.01 minimum
        success, main_result, trap_result = await self.executor.execute_dual_position(
            main_token_id="test-up",
            trap_token_id="test-down",
            total_budget_usd=0.10,  # This makes trap too small
            main_allocation_pct=0.85,
            trap_allocation_pct=0.15,
            max_trap_price=0.25
        )

        # Should succeed with single position only
        self.assertTrue(success)
        self.assertTrue(main_result.success)
        self.assertFalse(trap_result.success)
        self.assertIn("Trap too small", trap_result.error)

    @patch.object(OrderExecutor, 'get_best_ask')
    async def test_execute_dual_position_normal(self, mock_get_ask):
        """Test normal dual position execution."""
        mock_get_ask.side_effect = [0.70, 0.30]  # UP at $0.70, DOWN at $0.30

        success, main_result, trap_result = await self.executor.execute_dual_position(
            main_token_id="test-up",
            trap_token_id="test-down",
            total_budget_usd=2.00,
            main_allocation_pct=0.90,
            trap_allocation_pct=0.10,
            max_trap_price=0.25
        )

        # Both should succeed
        self.assertTrue(success)
        self.assertTrue(main_result.success)
        self.assertTrue(trap_result.success)

        # Verify budget allocation
        main_cost = main_result.contracts_filled * main_result.avg_price
        trap_cost = trap_result.contracts_filled * trap_result.avg_price
        total_cost = main_cost + trap_cost

        # Should be approximately $2.00 (within rounding)
        self.assertAlmostEqual(total_cost, 2.00, places=2)

    def test_min_order_usd_constant(self):
        """Test MIN_ORDER_USD constant is correct."""
        self.assertEqual(MIN_ORDER_USD, 0.01)

    def test_simulation_fill_sizing(self):
        """Test simulation fill respects sizing rules."""
        config = ExecutionConfig(
            bet_amount_usd=0.50,
            price_offset=0.0,
            max_retries=1,
            max_entry_price=0.75
        )

        # Test normal fill
        result = self.executor._simulate_fill(config, 0.50)
        self.assertTrue(result.success)
        self.assertEqual(result.contracts_filled, 1)  # $0.50 / $0.50 = 1 contract
        self.assertEqual(result.total_cost, 0.50)

        # Test fill with minimum adjustment
        config.bet_amount_usd = 0.005  # Below minimum
        result = self.executor._simulate_fill(config, 0.50)
        # Should adjust to minimum order size
        expected_contracts = 1  # $0.01 / $0.50 = 0.02 -> ceil to 1
        self.assertEqual(result.contracts_filled, expected_contracts)


if __name__ == '__main__':
    unittest.main()