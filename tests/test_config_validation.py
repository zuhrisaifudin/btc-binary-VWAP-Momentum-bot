#!/usr/bin/env python3
"""
Test suite for config validation.

Tests config loading, validation, and constraint checking.
"""

import unittest
import json
import tempfile
import os
from unittest.mock import patch

from main import load_config, validate_config


class TestConfigValidation(unittest.TestCase):
    """Test configuration loading and validation."""

    def setUp(self):
        """Create test configuration files."""
        # Valid config
        self.valid_config = {
            "market": {"interval_minutes": 5},
            "strategy": {
                "min_price": 0.60,
                "max_price": 0.90,
                "min_elapsed_sec": 60,
                "min_deviation_pct": 0.1,
                "max_deviation_pct": 100,
                "no_entry_before_end_sec": 30,
                "momentum_window_sec": 90,
                "vwap_window_sec": 60,
                "win_rate_csv": "data/win_rate.csv",
                "min_momentum_5s": 0.0,
                "min_volume_1m": 100
            },
            "entry": {
                "bet_amount_usd": 0.50,
                "price_offset": 0.02,
                "order_type": "FAK",
                "max_retries": 3,
                "retry_delay_ms": 300,
                "fill_timeout_ms": 1000,
                "min_contracts": 1,
                "min_order_usd": 0.01,
                "max_entry_price": 0.75,
                "ws_recovery_timeout_sec": 10,
                "max_daily_trades": 20,
                "daily_stop_loss_usd": -5.0
            },
            "hedge": {
                "enabled": False,
                "hedge_price": 0.02,
                "hedge_contracts": 1,
                "order_type": "GTD",
                "max_retries": 3,
                "retry_delay_ms": 300,
                "hedge_only_if_profit": True,
                "min_floating_profit_pct": 0.20
            },
            "dual_position": {
                "enabled": True,
                "total_budget_usd": 2.00,
                "main_allocation_pct": 0.90,
                "trap_allocation_pct": 0.10,
                "max_trap_price": 0.25,
                "order_type": "FAK"
            },
            "simulation": {"enabled": False},
            "telegram": {"enabled": True},
            "web_dashboard": {"enabled": True, "host": "127.0.0.1", "port": 8765},
            "logging": {"level": "INFO", "file_rotation_hours": 3}
        }

        # Create temp file
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(self.valid_config, self.temp_file)
        self.temp_file.close()

    def tearDown(self):
        """Clean up temp file."""
        os.unlink(self.temp_file.name)

    def test_load_config(self):
        """Test config loading."""
        with patch('main.CONFIG_PATH', self.temp_file.name):
            config = load_config()
            self.assertIsNotNone(config)
            self.assertEqual(config.market.interval_minutes, 5)
            self.assertEqual(config.entry.bet_amount_usd, 0.50)

    def test_validate_config_valid(self):
        """Test validation of valid config."""
        with patch('main.CONFIG_PATH', self.temp_file.name):
            config = load_config()
            errors = validate_config(config)
            self.assertEqual(len(errors), 0)

    def test_validate_config_invalid_allocation(self):
        """Test invalid allocation percentages."""
        # Create invalid config - allocations don't sum to 1
        invalid_config = self.valid_config.copy()
        invalid_config["dual_position"]["main_allocation_pct"] = 0.8
        invalid_config["dual_position"]["trap_allocation_pct"] = 0.3  # Sum = 1.1

        with open(self.temp_file.name, 'w') as f:
            json.dump(invalid_config, f)

        config = load_config()
        errors = validate_config(config)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("allocation" in err.lower() for err in errors))

    def test_validate_config_invalid_time_window(self):
        """Test invalid time window configuration."""
        # Create invalid config - entry window would be negative
        invalid_config = self.valid_config.copy()
        invalid_config["strategy"]["min_elapsed_sec"] = 200
        invalid_config["strategy"]["no_entry_before_end_sec"] = 210  # > min_elapsed

        with open(self.temp_file.name, 'w') as f:
            json.dump(invalid_config, f)

        config = load_config()
        errors = validate_config(config)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("time window" in err.lower() for err in errors))

    def test_validate_config_invalid_trap_price(self):
        """Test invalid trap price configuration."""
        # Create invalid config - trap price too high relative to max_price
        invalid_config = self.valid_config.copy()
        invalid_config["dual_position"]["max_trap_price"] = 0.95  # > max_price (0.90)

        with open(self.temp_file.name, 'w') as f:
            json.dump(invalid_config, f)

        config = load_config()
        errors = validate_config(config)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("trap" in err.lower() for err in errors))

    def test_validate_config_missing_required_field(self):
        """Test validation with missing required field."""
        # Remove a required field
        invalid_config = self.valid_config.copy()
        del invalid_config["entry"]["bet_amount_usd"]

        with open(self.temp_file.name, 'w') as f:
            json.dump(invalid_config, f)

        config = load_config()
        errors = validate_config(config)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("bet_amount" in err.lower() for err in errors))

    def test_validate_config_invalid_values(self):
        """Test validation of invalid value ranges."""
        # Create config with invalid values
        invalid_config = self.valid_config.copy()
        invalid_config["strategy"]["min_price"] = 1.5  # > max_price
        invalid_config["strategy"]["min_deviation_pct"] = -10  # Negative percentage
        invalid_config["entry"]["max_daily_trades"] = 0  # Zero daily trades

        with open(self.temp_file.name, 'w') as f:
            json.dump(invalid_config, f)

        config = load_config()
        errors = validate_config(config)
        self.assertGreater(len(errors), 0)
        # Should have errors for all invalid values
        self.assertTrue(any("min_price" in err.lower() for err in errors))
        self.assertTrue(any("deviation" in err.lower() for err in errors))
        self.assertTrue(any("daily_trades" in err.lower() for err in errors))

    def test_validate_config_simulation_mode(self):
        """Test validation in simulation mode."""
        # Enable simulation mode
        valid_config = self.valid_config.copy()
        valid_config["simulation"]["enabled"] = True

        with open(self.temp_file.name, 'w') as f:
            json.dump(valid_config, f)

        config = load_config()
        errors = validate_config(config)
        # Should have fewer requirements in simulation mode
        self.assertLessEqual(len(errors), 2)  # Maybe only path errors


if __name__ == '__main__':
    unittest.main()