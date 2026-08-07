#!/usr/bin/env python3
"""
Metrics & Monitoring — Prometheus + Grafana Integration

Bot V3 Observability Layer:
- Prometheus metrics export
- Real-time dashboards
- Alerting rules
- Performance tracking

Features:
- Counter metrics (orders, fills, errors)
- Gauge metrics (PnL, inventory, imbalance)
- Histogram metrics (latency, fill time)
- Health checks
- Metrics endpoint: /metrics
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, List, Any
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    CollectorRegistry,
    generate_latest,
    CONTENT_TYPE_LATEST,
    start_http_server,
)

logger = logging.getLogger("btc_live.metrics")

# Registry
REGISTRY = CollectorRegistry()

# ============================================================================
# COUNTERS — Cumulative events
# ============================================================================

ORDERS_TOTAL = Counter(
    "bot_orders_total",
    "Total number of orders placed",
    ["market", "side", "order_type"],  # labels
    registry=REGISTRY,
)

FILLS_TOTAL = Counter(
    "bot_fills_total",
    "Total number of fills received",
    ["market", "side"],
    registry=REGISTRY,
)

FILLS_REJECTED = Counter(
    "bot_fills_rejected_total",
    "Total number of fills rejected by guardrail",
    ["market", "reason"],
    registry=REGISTRY,
)

GUARDRAL_REJECTIONS = Counter(
    "bot_guardrail_rejections_total",
    "Total guardrail rejections",
    ["market", "rule"],
    registry=REGISTRY,
)

ERRORS_TOTAL = Counter(
    "bot_errors_total",
    "Total errors encountered",
    ["component", "error_type"],
    registry=REGISTRY,
)

WEBSOCKET_RECONNECTS = Counter(
    "bot_websocket_reconnects_total",
    "Total WebSocket reconnection attempts",
    ["stream_type"],
    registry=REGISTRY,
)

# ============================================================================
# GAUGES — Current state
# ============================================================================

PNL_CURRENT = Gauge(
    "bot_pnl_current",
    "Current unrealized PnL (USD)",
    ["market"],
    registry=REGISTRY,
)

PNL_REALIZED = Gauge(
    "bot_pnl_realized",
    "Realized PnL (USD)",
    registry=REGISTRY,
)

INVENTORY_UP = Gauge(
    "bot_inventory_up",
    "Current UP contracts held",
    ["market"],
    registry=REGISTRY,
)

INVENTORY_DOWN = Gauge(
    "bot_inventory_down",
    "Current DOWN contracts held",
    ["market"],
    registry=REGISTRY,
)

IMBALANCE = Gauge(
    "bot_imbalance",
    "Inventory imbalance (UP - DOWN)",
    ["market"],
    registry=REGISTRY,
)

CASH_BALANCE = Gauge(
    "bot_cash_balance",
    "Current cash balance (USDC)",
    registry=REGISTRY,
)

GUARDRAIL_MODE = Gauge(
    "bot_guardrail_mode",
    "Current guardrail mode (0=off, 1=spread_positive, 2=risk_free_only)",
    registry=REGISTRY,
)

WORKER_STATUS = Gauge(
    "bot_worker_status",
    "Worker status per market (0=stopped, 1=running)",
    ["market"],
    registry=REGISTRY,
)

WEBSOCKET_CONNECTED = Gauge(
    "bot_websocket_connected",
    "WebSocket connection status (0=disconnected, 1=connected)",
    ["stream_type"],
    registry=REGISTRY,
)

# ============================================================================
# HISTOGRAMS — Distribution of values
# ============================================================================

ORDER_LATENCY = Histogram(
    "bot_order_latency_seconds",
    "Time to place order (seconds)",
    ["market", "side"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)

FILL_LATENCY = Histogram(
    "bot_fill_latency_seconds",
    "Time from order to fill (seconds)",
    ["market"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
    registry=REGISTRY,
)

QUOTE_LATENCY = Histogram(
    "bot_quote_latency_seconds",
    "Time to generate quote (seconds)",
    ["market"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1),
    registry=REGISTRY,
)

GUARDRAIL_LATENCY = Histogram(
    "bot_guardrail_latency_seconds",
    "Time to evaluate guardrail (seconds)",
    ["market"],
    buckets=(0.0001, 0.0005, 0.001, 0.0025, 0.005, 0.01),
    registry=REGISTRY,
)

# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class MetricSnapshot:
    """Snapshot of all current metrics."""

    timestamp: datetime
    pnl_current: float = 0.0
    pnl_realized: float = 0.0
    cash_balance: float = 0.0
    total_orders: int = 0
    total_fills: int = 0
    total_rejections: int = 0
    active_workers: int = 0
    websocket_connected: bool = True


@dataclass
class MarketMetrics:
    """Per-market metrics."""

    market: str
    inventory_up: int = 0
    inventory_down: int = 0
    imbalance: int = 0
    pnl_unrealized: float = 0.0
    orders_placed: int = 0
    fills_received: int = 0
    last_fill_time: Optional[datetime] = None


# ============================================================================
# Metrics Manager
# ============================================================================


class MetricsManager:
    """
    Centralized metrics management for Bot V3.

    Usage:
        metrics = MetricsManager()
        metrics.start_http_server(port=9090)

        # Record metrics
        metrics.record_order("BTC-DEC31", "YES", "FAK")
        metrics.record_fill("BTC-DEC31", "YES", 50, 0.52)
        metrics.update_pnl("BTC-DEC31", 12.50)
        metrics.update_inventory("BTC-DEC31", up=100, down=86)
    """

    def __init__(self):
        self.start_time = datetime.utcnow()
        self.market_metrics: Dict[str, MarketMetrics] = {}
        self.snapshot_history: List[MetricSnapshot] = []
        logger.info("MetricsManager initialized")

    def start_http_server(self, port: int = 9090):
        """Start Prometheus metrics HTTP server."""
        try:
            start_http_server(port, registry=REGISTRY)
            logger.info(f"Prometheus metrics server started on port {port}")
            logger.info(f"Metrics endpoint: http://localhost:{port}/metrics")
        except Exception as e:
            logger.error(f"Failed to start metrics server: {e}")
            raise

    def get_latest_metrics(self) -> str:
        """Get latest metrics in Prometheus format."""
        return generate_latest(REGISTRY).decode("utf-8")

    # ------------------------------------------------------------------------
    # Order Tracking
    # ------------------------------------------------------------------------

    def record_order(self, market: str, side: str, order_type: str = "FAK"):
        """Record an order placement."""
        ORDERS_TOTAL.labels(market=market, side=side, order_type=order_type).inc()
        logger.debug(f"Order recorded: {market} {side} {order_type}")

    def record_order_latency(self, market: str, side: str, latency_sec: float):
        """Record order placement latency."""
        ORDER_LATENCY.labels(market=market, side=side).observe(latency_sec)

    # ------------------------------------------------------------------------
    # Fill Tracking
    # ------------------------------------------------------------------------

    def record_fill(self, market: str, side: str, contracts: int, price: float):
        """Record a fill event."""
        FILLS_TOTAL.labels(market=market, side=side).inc()
        
        if market not in self.market_metrics:
            self.market_metrics[market] = MarketMetrics(market=market)
        
        mm = self.market_metrics[market]
        if side.upper() == "YES" or side.upper() == "UP":
            mm.inventory_up += contracts
        else:
            mm.inventory_down += contracts
        
        mm.imbalance = mm.inventory_up - mm.inventory_down
        mm.fills_received += 1
        mm.last_fill_time = datetime.utcnow()
        
        # Update gauges
        INVENTORY_UP.labels(market=market).set(mm.inventory_up)
        INVENTORY_DOWN.labels(market=market).set(mm.inventory_down)
        IMBALANCE.labels(market=market).set(mm.imbalance)
        
        logger.debug(f"Fill recorded: {market} {side} {contracts}@{price:.4f}")

    def record_fill_latency(self, market: str, latency_sec: float):
        """Record fill latency (order → fill)."""
        FILL_LATENCY.labels(market=market).observe(latency_sec)

    # ------------------------------------------------------------------------
    # Guardrail Tracking
    # ------------------------------------------------------------------------

    def record_guardrail_rejection(self, market: str, rule: str):
        """Record a guardrail rejection."""
        GUARDRAL_REJECTIONS.labels(market=market, rule=rule).inc()
        logger.debug(f"Guardrail rejection: {market} - {rule}")

    def record_fill_rejection(self, market: str, reason: str):
        """Record a fill rejection."""
        FILLS_REJECTED.labels(market=market, reason=reason).inc()

    def record_guardrail_latency(self, market: str, latency_sec: float):
        """Record guardrail evaluation latency."""
        GUARDRAIL_LATENCY.labels(market=market).observe(latency_sec)

    # ------------------------------------------------------------------------
    # PnL Tracking
    # ------------------------------------------------------------------------

    def update_pnl(self, market: str, unrealized_pnl: float):
        """Update unrealized PnL for a market."""
        PNL_CURRENT.labels(market=market).set(unrealized_pnl)
        
        if market in self.market_metrics:
            self.market_metrics[market].pnl_unrealized = unrealized_pnl

    def update_realized_pnl(self, total_pnl: float):
        """Update total realized PnL."""
        PNL_REALIZED.set(total_pnl)

    # ------------------------------------------------------------------------
    # Inventory Tracking
    # ------------------------------------------------------------------------

    def update_inventory(self, market: str, up: int, down: int):
        """Update inventory counts."""
        if market not in self.market_metrics:
            self.market_metrics[market] = MarketMetrics(market=market)
        
        mm = self.market_metrics[market]
        mm.inventory_up = up
        mm.inventory_down = down
        mm.imbalance = up - down
        
        INVENTORY_UP.labels(market=market).set(up)
        INVENTORY_DOWN.labels(market=market).set(down)
        IMBALANCE.labels(market=market).set(mm.imbalance)

    # ------------------------------------------------------------------------
    # Cash Balance
    # ------------------------------------------------------------------------

    def update_cash_balance(self, balance: float):
        """Update cash balance."""
        CASH_BALANCE.set(balance)

    # ------------------------------------------------------------------------
    # Guardrail Mode
    # ------------------------------------------------------------------------

    def set_guardrail_mode(self, mode: str):
        """Set current guardrail mode."""
        mode_map = {"off": 0, "spread_positive": 1, "risk_free_only": 2}
        mode_value = mode_map.get(mode, 0)
        GUARDRAIL_MODE.set(mode_value)
        logger.info(f"Guardrail mode set to: {mode} ({mode_value})")

    # ------------------------------------------------------------------------
    # Worker Status
    # ------------------------------------------------------------------------

    def set_worker_status(self, market: str, running: bool):
        """Set worker status for a market."""
        status = 1 if running else 0
        WORKER_STATUS.labels(market=market).set(status)

    # ------------------------------------------------------------------------
    # WebSocket Status
    # ------------------------------------------------------------------------

    def set_websocket_status(self, stream_type: str, connected: bool):
        """Set WebSocket connection status."""
        status = 1 if connected else 0
        WEBSOCKET_CONNECTED.labels(stream_type=stream_type).set(status)

    def record_websocket_reconnect(self, stream_type: str):
        """Record WebSocket reconnection attempt."""
        WEBSOCKET_RECONNECTS.labels(stream_type=stream_type).inc()

    # ------------------------------------------------------------------------
    # Error Tracking
    # ------------------------------------------------------------------------

    def record_error(self, component: str, error_type: str):
        """Record an error."""
        ERRORS_TOTAL.labels(component=component, error_type=error_type).inc()
        logger.error(f"Error recorded: {component} - {error_type}")

    # ------------------------------------------------------------------------
    # Quote Latency
    # ------------------------------------------------------------------------

    def record_quote_latency(self, market: str, latency_sec: float):
        """Record quote generation latency."""
        QUOTE_LATENCY.labels(market=market).observe(latency_sec)

    # ------------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------------

    def take_snapshot(self) -> MetricSnapshot:
        """Take a snapshot of current metrics."""
        total_orders = sum(
            ORDERS_TOTAL.collect()[0].samples[0].value
            for _ in range(1)
        )
        
        snapshot = MetricSnapshot(
            timestamp=datetime.utcnow(),
            pnl_current=PNL_CURRENT._value.get() or 0.0,
            pnl_realized=PNL_REALIZED._value.get() or 0.0,
            cash_balance=CASH_BALANCE._value.get() or 0.0,
            total_orders=int(total_orders),
            active_workers=sum(
                1 for m in self.market_metrics.values()
                if m.last_fill_time is not None
            ),
            websocket_connected=WEBSOCKET_CONNECTED._value.get() == 1,
        )
        
        self.snapshot_history.append(snapshot)
        if len(self.snapshot_history) > 1000:
            self.snapshot_history.pop(0)
        
        return snapshot

    def get_market_summary(self, market: str) -> Optional[MarketMetrics]:
        """Get metrics summary for a specific market."""
        return self.market_metrics.get(market)

    def get_all_markets(self) -> List[str]:
        """Get list of all tracked markets."""
        return list(self.market_metrics.keys())


# ============================================================================
# Singleton Instance
# ============================================================================

METRICS = MetricsManager()


def get_metrics() -> MetricsManager:
    """Get global metrics manager instance."""
    return METRICS


# ============================================================================
# Grafana Dashboard JSON Template
# ============================================================================

GRAFANA_DASHBOARD_JSON = {
    "dashboard": {
        "title": "Bot V3 — Real-time Monitoring",
        "panels": [
            {
                "title": "PnL (Realized & Unrealized)",
                "type": "graph",
                "targets": [
                    {"expr": "bot_pnl_realized", "legendFormat": "Realized"},
                    {"expr": "sum(bot_pnl_current)", "legendFormat": "Unrealized"},
                ],
            },
            {
                "title": "Inventory Imbalance",
                "type": "graph",
                "targets": [
                    {"expr": "bot_imbalance", "legendFormat": "{{market}}"},
                ],
            },
            {
                "title": "Orders vs Fills",
                "type": "graph",
                "targets": [
                    {"expr": "rate(bot_orders_total[1m])", "legendFormat": "Orders/s"},
                    {"expr": "rate(bot_fills_total[1m])", "legendFormat": "Fills/s"},
                ],
            },
            {
                "title": "Guardrail Rejections",
                "type": "graph",
                "targets": [
                    {"expr": "rate(bot_guardrail_rejections_total[1m])", "legendFormat": "{{rule}}"},
                ],
            },
            {
                "title": "Order Latency (p95)",
                "type": "graph",
                "targets": [
                    {"expr": "histogram_quantile(0.95, rate(bot_order_latency_seconds_bucket[5m]))", "legendFormat": "p95"},
                ],
            },
            {
                "title": "Worker Status",
                "type": "stat",
                "targets": [
                    {"expr": "sum(bot_worker_status)", "legendFormat": "Active Workers"},
                ],
            },
        ],
    }
}


def get_grafana_dashboard_json() -> dict:
    """Get Grafana dashboard JSON template."""
    return GRAFANA_DASHBOARD_JSON


if __name__ == "__main__":
    # Demo: Start metrics server and simulate some data
    import time
    
    print("Starting Metrics Demo...")
    METRICS.start_http_server(port=9090)
    METRICS.set_guardrail_mode("risk_free_only")
    
    # Simulate some activity
    for i in range(10):
        market = "BTC-TEST"
        METRICS.record_order(market, "YES", "FAK")
        METRICS.record_order_latency(market, "YES", 0.05 + i * 0.01)
        METRICS.record_fill(market, "YES", 10, 0.52)
        METRICS.record_fill_latency(market, 0.3 + i * 0.05)
        METRICS.update_pnl(market, 5.0 + i * 0.5)
        METRICS.update_inventory(market, up=50 + i * 10, down=40 + i * 5)
        METRICS.set_worker_status(market, running=True)
        time.sleep(0.5)
    
    print(f"\nMetrics available at: http://localhost:9090/metrics")
    print("Press Ctrl+C to exit...")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nDemo stopped.")
