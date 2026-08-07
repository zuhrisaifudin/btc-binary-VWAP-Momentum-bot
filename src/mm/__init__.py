"""
src/mm/__init__.py — Package marker untuk modul market maker V3
"""

from .pnl_formula import (
    InventoryState,
    modal,
    pnl_settle,
    worst_case,
    spread_pair,
    sum_prices,
    decompose,
    project_fill,
)
from .guardrail import (
    GuardrailMode,
    GuardrailConfig,
    GuardrailDecision,
    Guardrail,
    create_guardrail,
)

__all__ = [
    # pnl_formula
    "InventoryState",
    "modal",
    "pnl_settle",
    "worst_case",
    "spread_pair",
    "sum_prices",
    "decompose",
    "project_fill",
    # guardrail
    "GuardrailMode",
    "GuardrailConfig",
    "GuardrailDecision",
    "Guardrail",
    "create_guardrail",
    # quotes
    "ExecutionPhase",
    "QuoteConfig",
    "BookLevel",
    "OrderBook",
    "Quote",
    "QuoteEngine",
]
