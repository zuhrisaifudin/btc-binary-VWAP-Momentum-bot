#!/usr/bin/env python3
"""
Test suite for win rate table functionality.

Tests edge cases, bin clamping, and win rate calculations.
"""

import unittest
import os
import tempfile
from unittest.mock import patch

from src.indicators import WinRateTable


class TestWinRateTable(unittest.TestCase):
    """Test WinRateTable functionality."""

    def setUp(self):
        """Create a temporary CSV file for testing."""
        # Create test CSV data
        self.csv_content = """price,minute,win_count,total_count
0.50,0,5,10
0.60,0,7,10
0.70,0,8,10
0.80,0,6,10
0.90,0,4,10
0.50,15,6,10
0.60,15,8,10
0.70,15,9,10
0.80,15,7,10
0.90,15,5,10
        """

        # Create temporary file
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
        self.temp_file.write(self.csv_content)
        self.temp_file.close()

    def tearDown(self):
        """Clean up temporary file."""
        os.unlink(self.temp_file.name)

    def test_winrate_table_creation(self):
        """Test WinRateTable creation with valid CSV."""
        table = WinRateTable(self.temp_file.name)
        self.assertIsNotNone(table)
        self.assertEqual(len(table.data), 10)  # 10 rows in test data

    def test_winrate_table_invalid_file(self):
        """Test WinRateTable with invalid/non-existent file."""
        # Should not crash, just have empty data
        table = WinRateTable("non_existent_file.csv")
        self.assertIsNotNone(table)
        self.assertEqual(len(table.data), 0)

    def test_get_winrate_normal_case(self):
        """Test normal win rate lookup."""
        table = WinRateTable(self.temp_file.name)

        # Test exact match
        winrate = table.get_winrate(0.60, 0, 15)
        self.assertEqual(winrate, 0.7)  # 7/10 from data

        # Test exact match at minute 15
        winrate = table.get_winrate(0.80, 15, 15)
        self.assertEqual(winrate, 0.7)  # 7/10 from data

    def test_get_winrate_bin_clamping(self):
        """Test price bin clamping."""
        table = WinRateTable(self.temp_file.name)

        # Test price below minimum - should clamp to lowest bin
        winrate = table.get_winrate(0.40, 0, 15)  # Below 0.50
        # Should clamp to 0.50 bin (win_rate=0.5)
        self.assertEqual(winrate, 0.5)

        # Test price above maximum - should clamp to highest bin
        winrate = table.get_winrate(1.00, 0, 15)  # Above 0.90
        # Should clamp to 0.90 bin (win_rate=0.4)
        self.assertEqual(winrate, 0.4)

    def test_get_winrate_minute_interpolation(self):
        """Test minute interpolation between intervals."""
        table = WinRateTable(self.temp_file.name)

        # Test minute between 0 and 15 - should average the two
        # At minute 7.5 (halfway between 0 and 15)
        # 0.60 price: minute 0 -> 0.7, minute 15 -> 0.8
        # Expected: (0.7 + 0.8) / 2 = 0.75
        winrate = table.get_winrate(0.60, 7, 15)
        self.assertAlmostEqual(winrate, 0.75, places=2)

        # Test minute beyond range - should clamp to nearest
        winrate = table.get_winrate(0.70, 30, 15)  # Beyond 15 minutes
        # Should clamp to minute 15 (win_rate=0.9)
        self.assertEqual(winrate, 0.9)

    def test_get_winrate_edge_cases(self):
        """Test various edge cases."""
        table = WinRateTable(self.temp_file.name)

        # Test with no matching data
        winrate = table.get_winrate(0.55, 0, 15)  # No exact match for 0.55
        # Should interpolate between 0.50 and 0.60
        # 0.50: 0.5, 0.60: 0.7, expected: ~0.6
        self.assertTrue(0.5 <= winrate <= 0.7)

        # Test with zero trades (should return None)
        # Create CSV with zero trades for a price
        csv_zero = """price,minute,win_count,total_count
0.50,0,0,0
        """
        temp_zero = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
        temp_zero.write(csv_zero)
        temp_zero.close()

        table_zero = WinRateTable(temp_zero.name)
        winrate = table_zero.get_winrate(0.50, 0, 15)
        self.assertIsNone(winrate)

        os.unlink(temp_zero.name)

    def test_get_winrate_invalid_minute_interval(self):
        """Test with invalid minute interval."""
        table = WinRateTable(self.temp_file.name)

        # Test minute interval that doesn't match data
        # Should still work with existing data
        winrate = table.get_winrate(0.70, 0, 30)  # Data stored at 15 min intervals
        # Should use available minute 0 data
        self.assertEqual(winrate, 0.8)

    def test_winrate_data_quality(self):
        """Test data quality checks."""
        table = WinRateTable(self.temp_file.name)

        # Verify all win rates are between 0 and 1
        for row in table.data:
            if row['total_count'] > 0:
                win_rate = row['win_count'] / row['total_count']
                self.assertGreaterEqual(win_rate, 0.0)
                self.assertLessEqual(win_rate, 1.0)

        # Verify no division by zero in existing data
        for row in table.data:
            self.assertGreater(row['total_count'], 0)


if __name__ == '__main__':
    unittest.main()