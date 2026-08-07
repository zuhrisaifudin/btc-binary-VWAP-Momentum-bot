"""
FastAPI routers untuk Control Plane Bot V3.

Endpoints:
- GET /v1/health - Health check sistem
- GET /v1/markets - List semua markets
- POST /v1/markets/start - Start market worker
- POST /v1/markets/stop - Stop market worker
- GET /v1/markets/{market}/status - Status market
- GET /v1/markets/{market}/quote - Quote terkini
- GET /v1/markets/{market}/pnl - Analisis PnL
- POST /v1/orders/submit - Submit order manual
- POST /v1/orders/cancel - Cancel order
- GET /v1/config - Get konfigurasi
- PUT /v1/config - Update konfigurasi
- GET /v1/events - Event logs
- WebSocket /v1/ws/dashboard - Real-time dashboard
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from src.api.schemas import (
    CancelOrderRequest,
    ConfigResponse,
    ErrorResponse,
    GuardrailCheckResponse,
    GuardrailMode,
    MarketStatusResponse,
    PnLAnalysisResponse,
    QuoteResponse,
    StartMarketRequest,
    StopMarketRequest,
    SubmitOrderRequest,
    SystemHealthResponse,
    UpdateConfigRequest,
    WorkerHealthResponse,
    WorkerStatus,
    WSBookSnapshot,
    WSFillEvent,
    WSGuardrailAlert,
    WSWorkerStatus,
)
from src.infra.websocket_streams import BookSnapshot, FillEvent
from src.mm.pnl_formula import InventoryState
from src.workers.market_worker import WorkerManager

logger = logging.getLogger(__name__)

# Router instance
router = APIRouter(prefix="/v1", tags=["Bot V3 Control Plane"])

# Global state (akan di-inject dari main app)
_worker_manager: Optional[WorkerManager] = None
_config: Dict[str, Any] = {}
_start_time: float = 0.0
_websocket_clients: List[WebSocket] = []


def set_global_state(
    worker_manager: WorkerManager,
    config: Dict[str, Any],
    start_time: float,
):
    """Set global state (dipanggil saat startup)."""
    global _worker_manager, _config, _start_time
    _worker_manager = worker_manager
    _config = config
    _start_time = start_time


async def broadcast_ws(message: Dict[str, Any]):
    """Broadcast message ke semua WebSocket clients."""
    disconnected = []
    
    for client in _websocket_clients:
        try:
            await client.send_json(message)
        except Exception:
            disconnected.append(client)
    
    # Remove disconnected clients
    for client in disconnected:
        _websocket_clients.remove(client)


# ============================================================================
# Health & Status Endpoints
# ============================================================================

@router.get("/health", response_model=SystemHealthResponse)
async def health_check():
    """Health check sistem."""
    if _worker_manager is None:
        raise HTTPException(status_code=503, detail="Worker manager not initialized")
    
    health = _worker_manager.health_status()
    
    active = sum(1 for h in health.values() if h["running"])
    stopped = sum(1 for h in health.values() if not h["running"])
    
    return SystemHealthResponse(
        total_markets=len(health),
        active_workers=active,
        stopped_workers=stopped,
        error_workers=0,  # TODO: Track errors
        websocket_connected=len(_websocket_clients) > 0,
        api_uptime_seconds=datetime.utcnow().timestamp() - _start_time,
        markets={
            market: MarketStatusResponse(
                market=market,
                worker_status=WorkerStatus.RUNNING if h["running"] else WorkerStatus.STOPPED,
                guardrail_mode=GuardrailMode.RISK_FREE_ONLY,  # TODO: Get from worker
                time_in_cycle=h["time_in_cycle"],
                open_orders_count=h["open_orders"],
            )
            for market, h in health.items()
        }
    )


@router.get("/markets", response_model=List[str])
async def list_markets():
    """List semua markets yang terdaftar."""
    if _worker_manager is None:
        return []
    
    return list(_worker_manager._workers.keys())


@router.get("/markets/{market}/status", response_model=MarketStatusResponse)
async def get_market_status(market: str):
    """Status detail satu market."""
    if _worker_manager is None:
        raise HTTPException(status_code=503, detail="Worker manager not initialized")
    
    worker = _worker_manager.get_worker(market)
    if worker is None:
        raise HTTPException(status_code=404, detail=f"Market {market} not found")
    
    health = _worker_manager.health_status().get(market, {})
    
    return MarketStatusResponse(
        market=market,
        worker_status=WorkerStatus.RUNNING if health.get("running", False) else WorkerStatus.STOPPED,
        guardrail_mode=worker.guardrail_mode,
        time_in_cycle=health.get("time_in_cycle", 0),
        open_orders_count=health.get("open_orders", 0),
        inventory={"pu": worker.state.inventory.pu, "pd": worker.state.inventory.pd}
    )


# ============================================================================
# Market Control Endpoints
# ============================================================================

@router.post("/markets/start")
async def start_market(request: StartMarketRequest):
    """Start market worker."""
    if _worker_manager is None:
        raise HTTPException(status_code=503, detail="Worker manager not initialized")
    
    # Validate guardrail mode untuk live
    if request.guardrail_mode == GuardrailMode.OFF:
        logger.warning(f"Attempted to start {request.market} with mode=OFF (DILARANG!)")
        # Tetap izinkan untuk testing/simulasi
    
    # Add worker jika belum ada
    if request.market not in _worker_manager._workers:
        _worker_manager.add_worker(
            market=request.market,
            guardrail_mode=request.guardrail_mode,
            config_override=request.config_override
        )
    
    # Start worker
    await _worker_manager.start_worker(request.market)
    
    # Broadcast via WebSocket
    await broadcast_ws({
        "type": "worker_status",
        "market": request.market,
        "status": "running",
        "guardrail_mode": request.guardrail_mode.value
    })
    
    return {"message": f"Market {request.market} started", "mode": request.guardrail_mode.value}


@router.post("/markets/stop")
async def stop_market(request: StopMarketRequest):
    """Stop market worker."""
    if _worker_manager is None:
        raise HTTPException(status_code=503, detail="Worker manager not initialized")
    
    if request.cancel_orders:
        # TODO: Cancel all orders untuk market ini
        logger.info(f"Cancelling all orders for {request.market}")
    
    await _worker_manager.stop_worker(request.market)
    
    # Broadcast via WebSocket
    await broadcast_ws({
        "type": "worker_status",
        "market": request.market,
        "status": "stopped"
    })
    
    return {"message": f"Market {request.market} stopped"}


# ============================================================================
# Quote & PnL Endpoints
# ============================================================================

@router.get("/markets/{market}/quote", response_model=QuoteResponse)
async def get_market_quote(market: str):
    """Quote terkini untuk market."""
    if _worker_manager is None:
        raise HTTPException(status_code=503, detail="Worker manager not initialized")
    
    worker = _worker_manager.get_worker(market)
    if worker is None:
        raise HTTPException(status_code=404, detail=f"Market {market} not found")
    
    if worker.state.last_book is None:
        raise HTTPException(status_code=404, detail="No book data available")
    
    # Generate quote
    from src.mm.quotes import QuoteRequest
    request = QuoteRequest(
        market=market,
        book=worker.state.last_book,
        inventory=worker.state.inventory,
        time_in_cycle=worker.state.time_in_cycle()
    )
    
    quote = worker.quote_engine.generate_quote(request)
    if quote is None:
        raise HTTPException(status_code=400, detail="Failed to generate quote")
    
    return QuoteResponse(
        market=market,
        bid_price=quote.bid_price,
        bid_size=quote.bid_size,
        ask_price=quote.ask_price,
        ask_size=quote.ask_size,
        spread=quote.spread,
        mid_price=quote.mid_price
    )


@router.get("/markets/{market}/pnl", response_model=PnLAnalysisResponse)
async def get_market_pnl(market: str):
    """Analisis PnL untuk market."""
    if _worker_manager is None:
        raise HTTPException(status_code=503, detail="Worker manager not initialized")
    
    worker = _worker_manager.get_worker(market)
    if worker is None:
        raise HTTPException(status_code=404, detail=f"Market {market} not found")
    
    inv = worker.state.inventory
    
    # Hitung metrics
    from src.mm.pnl_formula import modal, pnl_settle, worst_case, decompose
    
    inv_value = inv.pu + inv.pd  # Simplified
    m = modal(inv)
    pnl = pnl_settle(inv)
    wc = worst_case(inv)
    pu_pd = decompose(inv)
    
    return PnLAnalysisResponse(
        market=market,
        inventory_value=inv_value,
        modal=m,
        pnl_settle=pnl,
        worst_case=wc,
        pu_pd_sum=pu_pd["Pu"] + pu_pd["Pd"],
        is_risk_free=(pu_pd["Pu"] + pu_pd["Pd"] < 1) and (wc >= 0),
        imbalance=abs(inv.pu - inv.pd)
    )


# ============================================================================
# Manual Order Endpoints
# ============================================================================

@router.post("/orders/submit")
async def submit_order(request: SubmitOrderRequest):
    """Submit order manual (override auto)."""
    if _worker_manager is None:
        raise HTTPException(status_code=503, detail="Worker manager not initialized")
    
    worker = _worker_manager.get_worker(request.market)
    if worker is None:
        raise HTTPException(status_code=404, detail=f"Market {request.market} not found")
    
    # TODO: Implement actual order submission
    logger.info(
        f"Manual order: {request.side} {request.size}@{request.price} on {request.market}"
    )
    
    return {
        "message": "Order submitted (simulated)",
        "market": request.market,
        "side": request.side.value,
        "price": request.price,
        "size": request.size
    }


@router.post("/orders/cancel")
async def cancel_order(request: CancelOrderRequest):
    """Cancel order."""
    if _worker_manager is None:
        raise HTTPException(status_code=503, detail="Worker manager not initialized")
    
    worker = _worker_manager.get_worker(request.market)
    if worker is None:
        raise HTTPException(status_code=404, detail=f"Market {request.market} not found")
    
    # TODO: Implement actual order cancellation
    logger.info(f"Cancelling order {request.order_id} on {request.market}")
    
    return {"message": f"Order {request.order_id} cancelled (simulated)"}


# ============================================================================
# Configuration Endpoints
# ============================================================================

@router.get("/config", response_model=ConfigResponse)
async def get_config():
    """Get konfigurasi saat ini."""
    if not _config:
        raise HTTPException(status_code=404, detail="Configuration not loaded")
    
    return ConfigResponse(
        guardrail_mode=GuardrailMode(_config.get("guardrail", {}).get("mode", "risk_free_only")),
        max_imbalance_shares=_config.get("guardrail", {}).get("max_imbalance_shares", 14),
        pair_margin=_config.get("guardrail", {}).get("pair_margin", 0.02),
        schedule=_config.get("schedule", {}),
        capital=_config.get("capital", {})
    )


@router.put("/config")
async def update_config(request: UpdateConfigRequest):
    """Update konfigurasi global."""
    global _config
    
    if request.guardrail_mode is not None:
        if "guardrail" not in _config:
            _config["guardrail"] = {}
        _config["guardrail"]["mode"] = request.guardrail_mode.value
        
        # Warning untuk mode OFF
        if request.guardrail_mode == GuardrailMode.OFF:
            logger.warning("CONFIG WARNING: Mode OFF aktif (DILARANG untuk live!)")
    
    if request.max_imbalance_shares is not None:
        if "guardrail" not in _config:
            _config["guardrail"] = {}
        _config["guardrail"]["max_imbalance_shares"] = request.max_imbalance_shares
    
    if request.pair_margin is not None:
        if "guardrail" not in _config:
            _config["guardrail"] = {}
        _config["guardrail"]["pair_margin"] = request.pair_margin
    
    if request.taker_until_s is not None or request.maker_only_below_s is not None:
        if "schedule" not in _config:
            _config["schedule"] = {}
        if request.taker_until_s is not None:
            _config["schedule"]["taker_until_s"] = request.taker_until_s
        if request.maker_only_below_s is not None:
            _config["schedule"]["maker_only_below_s"] = request.maker_only_below_s
    
    return {"message": "Configuration updated", "config": _config}


# ============================================================================
# Event Log Endpoint
# ============================================================================

@router.get("/events")
async def get_events(
    market: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100
):
    """Get event logs dengan filter."""
    # TODO: Implement actual event log storage & retrieval
    return {"total": 0, "filtered": 0, "entries": []}


# ============================================================================
# WebSocket Dashboard
# ============================================================================

@router.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    """WebSocket endpoint untuk real-time dashboard."""
    await websocket.accept()
    _websocket_clients.append(websocket)
    
    logger.info(f"WebSocket client connected. Total clients: {len(_websocket_clients)}")
    
    try:
        # Send initial status
        await websocket.send_json({
            "type": "connected",
            "timestamp": datetime.utcnow().isoformat(),
            "message": "Connected to Bot V3 Control Plane"
        })
        
        # Keep connection alive & handle messages
        while True:
            try:
                data = await websocket.receive_text()
                # Handle incoming messages (optional)
                logger.debug(f"WS message received: {data}")
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"WS error: {e}")
                break
    
    finally:
        _websocket_clients.remove(websocket)
        logger.info(f"WebSocket client disconnected. Total clients: {len(_websocket_clients)}")


# ============================================================================
# Event Handlers (untuk dipanggil dari worker/infra)
# ============================================================================

async def on_fill_event(fill: FillEvent):
    """Handle fill event - broadcast via WebSocket."""
    await broadcast_ws({
        "type": "fill",
        "market": fill.market,
        "side": fill.side,
        "price": fill.price,
        "size": fill.size,
        "fee": fill.fee,
        "is_maker": fill.is_maker
    })


async def on_book_snapshot(book: BookSnapshot):
    """Handle book snapshot - broadcast via WebSocket."""
    await broadcast_ws({
        "type": "book_snapshot",
        "market": book.market,
        "bids": book.bids[:10],  # Top 10 levels only
        "asks": book.asks[:10],
        "sequence": book.sequence
    })


async def on_guardrail_alert(market: str, reason: str, severity: str = "WARNING"):
    """Handle guardrail alert - broadcast via WebSocket."""
    await broadcast_ws({
        "type": "guardrail_alert",
        "market": market,
        "reason": reason,
        "severity": severity
    })
