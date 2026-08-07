"""
Observability Module — Bot V3

Metrics, logging, and monitoring for production deployment.
"""

from .metrics import (
    MetricsManager,
    MetricSnapshot,
    MarketMetrics,
    METRICS,
    get_metrics,
    get_grafana_dashboard_json,
)

__all__ = [
    "MetricsManager",
    "MetricSnapshot",
    "MarketMetrics",
    "METRICS",
    "get_metrics",
    "get_grafana_dashboard_json",
]
