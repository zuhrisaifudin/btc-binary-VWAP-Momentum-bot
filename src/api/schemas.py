"""
Schemas Pydantic untuk FastAPI Control Plane Bot V3.

Endpoint API v1 menggunakan schema ini untuk:
- Request validation
- Response serialization
- WebSocket message format
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============================================================================
# Enums
# ============================================================================

class GuardrailMode(str, Enum):
    RISK_FREE_ONLY = "risk_free_only"
    SPREAD_POSITIVE = "spread_positive"
    OFF = "off"  # DILARANG untuk live!


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


class WorkerStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


# ============================================================================
# Request Schemas
# ============================================================================

class StartMarketRequest(BaseModel):
    """Request untuk start market worker."""
    market: str = Field(..., description="Market ID, e.g., 'btc-usd'")
    guardrail_mode: GuardrailMode = Field(
        default=GuardrailMode.RISK_FREE_ONLY,
        description="Mode guardrail (WAJIB: risk_free_only untuk live)"
    )
    config_override: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Override konfigurasi per market"
    )


class StopMarketRequest(BaseModel):
    """Request untuk stop market worker."""
    market: str = Field(..., description="Market ID")
    cancel_orders: bool = Field(
        default=True,
        description="Apakah harus cancel semua order aktif"
    )


class UpdateConfigRequest(BaseModel):
    """Request untuk update konfigurasi global."""
    guardrail_mode: Optional[GuardrailMode] = None
    max_imbalance_shares: Optional[int] = None
    pair_margin: Optional[float] = None
    taker_until_s: Optional[int] = None
    maker_only_below_s: Optional[int] = None


class SubmitOrderRequest(BaseModel):
    """Request manual submit order (override auto)."""
    market: str
    side: OrderSide
    price: float
    size: float
    is_maker: bool = True


class CancelOrderRequest(BaseModel):
    """Request cancel order."""
    market: str
    order_id: str


# ============================================================================
# Response Schemas
# ============================================================================

class MarketStatusResponse(BaseModel):
    """Status satu market."""
    market: str
    worker_status: WorkerStatus
    guardrail_mode: GuardrailMode
    time_in_cycle: float = Field(..., description="Waktu sejak cycle dimulai (detik)")
    open_orders_count: int
    last_fill_time: Optional[datetime] = None
    inventory: Dict[str, Any] = Field(default_factory=dict)


class SystemHealthResponse(BaseModel):
    """Health status sistem."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    total_markets: int
    active_workers: int
    stopped_workers: int
    error_workers: int
    websocket_connected: bool
    api_uptime_seconds: float
    markets: Dict[str, MarketStatusResponse] = Field(default_factory=dict)


class WorkerHealthResponse(BaseModel):
    """Health status satu worker."""
    market: str
    running: bool
    task_done: Optional[bool]
    open_orders: int
    time_in_cycle: float


class GuardrailCheckResponse(BaseModel):
    """Hasil guardrail check."""
    allowed: bool
    reason: Optional[str] = None
    cancel_required: bool = False
    details: Dict[str, Any] = Field(default_factory=dict)


class QuoteResponse(BaseModel):
    """Quote yang dihasilkan."""
    market: str
    bid_price: float
    bid_size: float
    ask_price: float
    ask_size: float
    spread: float
    mid_price: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PnLAnalysisResponse(BaseModel):
    """Analisis PnL dari rumus."""
    market: str
    inventory_value: float
    modal: float
    pnl_settle: float
    worst_case: float
    pu_pd_sum: float
    is_risk_free: bool
    imbalance: float


class ConfigResponse(BaseModel):
    """Konfigurasi saat ini."""
    guardrail_mode: GuardrailMode
    max_imbalance_shares: int
    pair_margin: float
    schedule: Dict[str, int]
    capital: Dict[str, Any]
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================================================
# WebSocket Message Schemas
# ============================================================================

class WSMessageBase(BaseModel):
    """Base schema untuk WebSocket message."""
    type: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class WSBookSnapshot(WSMessageBase):
    """WebSocket message: Book snapshot."""
    type: str = "book_snapshot"
    market: str
    bids: List[List[float]]
    asks: List[List[float]]
    sequence: int


class WSFillEvent(WSMessageBase):
    """WebSocket message: Fill event."""
    type: str = "fill"
    market: str
    side: OrderSide
    price: float
    size: float
    fee: float
    fee_asset: str
    order_id: str
    is_maker: bool


class WSWorkerStatus(WSMessageBase):
    """WebSocket message: Worker status update."""
    type: str = "worker_status"
    market: str
    status: WorkerStatus
    open_orders: int
    time_in_cycle: float


class WSGuardrailAlert(WSMessageBase):
    """WebSocket message: Guardrail alert."""
    type: str = "guardrail_alert"
    market: str
    reason: str
    severity: str = Field(..., description="WARNING atau CRITICAL")
    details: Dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# Event Log Schemas
# ============================================================================

class EventLogEntry(BaseModel):
    """Entry log event."""
    timestamp: datetime
    event_type: str
    market: str
    message: str
    data: Optional[Dict[str, Any]] = None


class EventLogResponse(BaseModel):
    """Response log event dengan filter."""
    total: int
    filtered: int
    entries: List[EventLogEntry]


# ============================================================================
# Error Response
# ============================================================================

class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
