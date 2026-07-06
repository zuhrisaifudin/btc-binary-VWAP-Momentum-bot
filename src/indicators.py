#!/usr/bin/env python3
"""
Indicators module for BTC trading bot.

Contains VWAP, momentum, z-score, deviation calculations and WinRateTable.
"""

import csv
import statistics
import time
from collections import deque
from dataclasses import dataclass
from typing import List, Optional, Dict, Any


@dataclass
class Trade:
    """Trade data for VWAP and momentum calculations."""
    price: float
    volume: int
    timestamp: float


def get_trades_in_window(trades: deque, window_seconds: float) -> List[Trade]:
    """Get trades within time window."""
    now = time.time()
    cutoff = now - window_seconds
    return [t for t in trades if t.timestamp >= cutoff]


def calc_vwap(trades: List[Trade]) -> float:
    """Calculate Volume Weighted Average Price."""
    if not trades:
        return 0.0
    total_value = sum(t.price * t.volume for t in trades)
    total_volume = sum(t.volume for t in trades)
    return total_value / total_volume if total_volume > 0 else 0.0


def calc_deviation(current_price: float, vwap: float) -> float:
    """Calculate percentage deviation from VWAP."""
    if vwap == 0:
        return 0.0
    return ((current_price - vwap) / vwap) * 100


def calc_momentum(trades: deque, current_price: float, window: float = 120, avg_band: float = 1.5) -> Optional[float]:
    """
    Calculate price momentum as percentage change from average price in the past.

    Args:
        trades: List of historical trades
        current_price: Current market price
        window: Time window in seconds to look back
        avg_band: Band around window for averaging (seconds)

    Returns:
        Percentage change, or None if insufficient data
    """
    now = time.time()
    band_start = now - window - avg_band
    band_end = now - window + avg_band

    band_prices = [t.price for t in trades if band_start <= t.timestamp <= band_end]

    if not band_prices:
        return None

    avg_price_ago = sum(band_prices) / len(band_prices)
    if avg_price_ago == 0:
        return None

    return ((current_price - avg_price_ago) / avg_price_ago) * 100


def calc_zscore(trades: deque, current_price: float, window: float = 5) -> float:
    """Calculate z-score of current price relative to recent prices."""
    now = time.time()
    recent = [t for t in trades if t.timestamp >= now - window]
    if len(recent) < 2:
        return 0.0
    prices = [t.price for t in recent]
    mean_price = statistics.mean(prices)
    std_price = statistics.stdev(prices) if len(prices) > 1 else 0.001
    return (current_price - mean_price) / std_price if std_price > 0 else 0.0


class WinRateTable:
    """Win rate statistics table loaded from CSV."""

    def __init__(self, csv_path: str):
        self.data = {}
        self.price_ranges = []
        self._load(csv_path)

    def _load(self, csv_path: str):
        """Load win rate data from CSV file."""
        try:
            with open(csv_path, 'r') as f:
                reader = csv.reader(f)
                next(reader)  # Skip header
                for row in reader:
                    if not row or not row[0]:
                        continue
                    price_range = row[0]
                    self.price_ranges.append(price_range)
                    self.data[price_range] = {}
                    for i, val in enumerate(row[1:], start=0):
                        if val:
                            try:
                                self.data[price_range][i] = float(val)
                            except ValueError:
                                pass
        except Exception as e:
            # Log warning but don't crash - just use empty table
            pass

    def get_winrate(self, price: float, minute: int, interval_minutes: int = 15) -> Optional[float]:
        """
        Get win rate for given price and minute.

        Args:
            price: Current token price
            minute: Current minute in market session
            interval_minutes: Market interval length (affects minute clamping)

        Returns:
            Win rate as fraction (0-1), or None if no data
        """
        # Find matching price range
        price_range = None
        for pr in self.price_ranges:
            try:
                low, high = pr.split('-')
                if float(low) <= price <= float(high):
                    price_range = pr
                    break
            except Exception:
                continue

        # If no match and price is high, use highest range
        if not price_range and price > 0.99 and self.price_ranges:
            price_range = self.price_ranges[-1]

        if not price_range:
            return None

        # Clamp minute to valid range
        cap = max(0, interval_minutes - 1)
        minute = max(0, min(cap, minute))

        return self.data.get(price_range, {}).get(minute)