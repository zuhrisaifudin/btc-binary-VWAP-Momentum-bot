"""
API package untuk FastAPI Control Plane Bot V3.

Komponen:
- schemas: Pydantic models untuk request/response
- routes: FastAPI routers untuk semua endpoints
"""

from .schemas import (
    GuardrailMode,
    OrderSide,
    OrderStatus,
    WorkerStatus,
    StartMarketRequest,
    StopMarketRequest,
    UpdateConfigRequest,
    SubmitOrderRequest,
    CancelOrderRequest,
    MarketStatusResponse,
    SystemHealthResponse,
    WorkerHealthResponse,
    GuardrailCheckResponse,
    QuoteResponse,
    PnLAnalysisResponse,
    ConfigResponse,
    WSBookSnapshot,
    WSFillEvent,
    WSWorkerStatus,
    WSGuardrailAlert,
    ErrorResponse,
)

from .routes import (
    router,
    set_global_state,
    on_fill_event,
    on_book_snapshot,
    on_guardrail_alert,
)

__all__ = [
    # Schemas
    "GuardrailMode",
    "OrderSide",
    "OrderStatus",
    "WorkerStatus",
    "StartMarketRequest",
    "StopMarketRequest",
    "UpdateConfigRequest",
    "SubmitOrderRequest",
    "CancelOrderRequest",
    "MarketStatusResponse",
    "SystemHealthResponse",
    "WorkerHealthResponse",
    "GuardrailCheckResponse",
    "QuoteResponse",
    "PnLAnalysisResponse",
    "ConfigResponse",
    "WSBookSnapshot",
    "WSFillEvent",
    "WSWorkerStatus",
    "WSGuardrailAlert",
    "ErrorResponse",
    # Routes
    "router",
    "set_global_state",
    "on_fill_event",
    "on_book_snapshot",
    "on_guardrail_alert",
]
