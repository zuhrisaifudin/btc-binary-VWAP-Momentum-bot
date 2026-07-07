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
        self.data: List[Dict[str, Any]] = []
        self._load(csv_path)

    def _load(self, csv_path: str):
        """Load win rate data from CSV file."""
        try:
            with open(csv_path, 'r') as f:
                reader = csv.reader(f)
                header = next(reader)  # Skip header
                for row in reader:
                    if not row or len(row) < 4:
                        continue
                    try:
                        self.data.append({
                            'price': float(row[0]),
                            'minute': int(row[1]),
                            'win_count': int(row[2]),
                            'total_count': int(row[3])
                        })
                    except ValueError:
                        pass
        except Exception:
            self.data = []

    def get_winrate(self, price: float, minute: int, interval_minutes: int = 15) -> Optional[float]:
        """
        Get win rate for given price and minute with interpolation/clamping.
        """
        # Filter only valid rows with total_count > 0
        valid_rows = [r for r in self.data if r['total_count'] > 0]
        if not valid_rows:
            return None

        # Find unique prices and minutes
        prices = sorted(list(set(r['price'] for r in valid_rows)))
        minutes = sorted(list(set(r['minute'] for r in valid_rows)))

        if not prices or not minutes:
            return None

        # Clamp price and minute to available ranges
        price = max(prices[0], min(prices[-1], price))
        minute = max(minutes[0], min(minutes[-1], minute))

        # Helper function to get winrate for a specific coordinate
        def get_rate(p: float, m: int) -> Optional[float]:
            for r in valid_rows:
                if abs(r['price'] - p) < 1e-6 and r['minute'] == m:
                    return r['win_count'] / r['total_count']
            return None

        # Find closest price bins (p1 <= price <= p2)
        if price in prices:
            p1 = p2 = price
        else:
            p1 = max(p for p in prices if p < price)
            p2 = min(p for p in prices if p > price)

        # Find closest minute bins (m1 <= minute <= m2)
        if minute in minutes:
            m1 = m2 = minute
        else:
            m1 = max(m for m in minutes if m < minute)
            m2 = min(m for m in minutes if m > minute)

        # Retrieve win rates at the corners
        w11 = get_rate(p1, m1)
        w12 = get_rate(p1, m2)
        w21 = get_rate(p2, m1)
        w22 = get_rate(p2, m2)

        # Interpolate price at m1
        if w11 is not None and w21 is not None:
            if abs(p2 - p1) < 1e-6:
                wm1 = w11
            else:
                wm1 = w11 + (price - p1) / (p2 - p1) * (w21 - w11)
        elif w11 is not None:
            wm1 = w11
        elif w21 is not None:
            wm1 = w21
        else:
            wm1 = None

        # Interpolate price at m2
        if w12 is not None and w22 is not None:
            if abs(p2 - p1) < 1e-6:
                wm2 = w12
            else:
                wm2 = w12 + (price - p1) / (p2 - p1) * (w22 - w12)
        elif w12 is not None:
            wm2 = w12
        elif w22 is not None:
            wm2 = w22
        else:
            wm2 = None

        # Interpolate minute
        if wm1 is not None and wm2 is not None:
            if m2 == m1:
                return wm1
            else:
                return wm1 + (minute - m1) / (m2 - m1) * (wm2 - wm1)
        elif wm1 is not None:
            return wm1
        elif wm2 is not None:
            return wm2
        else:
            return None