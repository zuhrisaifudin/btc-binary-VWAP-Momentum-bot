"""
Main application untuk Bot V3 — FastAPI Control Plane + Worker Event-Driven.

Cara menjalankan:
    uvicorn src.main_v3:app --host 0.0.0.0 --port 8000 --reload

Atau untuk production:
    gunicorn src.main_v3:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
"""

import asyncio
import logging
import sys
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import components
from src.api import router as api_router
from src.api import set_global_state, on_fill_event, on_book_snapshot
from src.config_loader import load_config
from src.infra.websocket_streams import (
    ConnectionPool,
    create_connection_pool,
    BookSnapshot,
    FillEvent,
)
from src.workers.market_worker import WorkerManager, create_worker_manager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/bot_v3.log")
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="Bot V3 Control Plane",
    description="FastAPI Control Plane untuk Bot BTC Binary VWAP Momentum V3",
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware (untuk dashboard frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict di production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(api_router)


# ============================================================================
# Global State
# ============================================================================

_config: Optional[Dict[str, Any]] = None
_connection_pool: Optional[ConnectionPool] = None
_worker_manager: Optional[WorkerManager] = None
_start_time: float = 0.0


# ============================================================================
# Startup & Shutdown Events
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize semua komponen saat startup."""
    global _config, _connection_pool, _worker_manager, _start_time
    
    logger.info("=" * 60)
    logger.info("Bot V3 — FastAPI Control Plane + Worker Event-Driven")
    logger.info("=" * 60)
    
    _start_time = datetime.utcnow().timestamp()
    
    # Load konfigurasi
    try:
        _config = load_config("config.json")
        logger.info("Configuration loaded successfully")
        
        # Validasi guardrail mode
        guardrail_mode = _config.get("guardrail", {}).get("mode", "risk_free_only")
        if guardrail_mode == "off":
            logger.warning("⚠️  GUARDRAIL MODE OFF — DILARANG UNTUK LIVE TRADING!")
        else:
            logger.info(f"✓ Guardrail mode: {guardrail_mode}")
            
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        _config = {"guardrail": {"mode": "risk_free_only"}}
    
    # Initialize Worker Manager
    _worker_manager = create_worker_manager(_config)
    logger.info("Worker manager initialized")
    
    # Initialize Connection Pool
    _connection_pool = create_connection_pool()
    
    # Setup callbacks
    def on_book_callback(book: BookSnapshot):
        """Callback saat book snapshot diterima."""
        # Route ke worker
        if _worker_manager:
            _worker_manager.route_book_event(book)
        
        # Broadcast via WebSocket
        asyncio.create_task(on_book_snapshot(book))
    
    def on_fill_callback(fill: FillEvent):
        """Callback saat fill diterima."""
        # Route ke worker
        if _worker_manager:
            _worker_manager.route_fill_event(fill)
        
        # Broadcast via WebSocket
        asyncio.create_task(on_fill_event(fill))
    
    # Configure connection pool dengan callbacks
    _connection_pool.set_user_stream(
        api_key=_config.get("api_key", ""),
        on_fill=on_fill_callback
    )
    
    logger.info("Connection pool initialized with callbacks")
    
    # Set global state untuk API routes
    set_global_state(
        worker_manager=_worker_manager,
        config=_config,
        start_time=_start_time
    )
    
    # Start connection pool (background task)
    asyncio.create_task(_connection_pool.start())
    logger.info("Connection pool started")
    
    logger.info("=" * 60)
    logger.info("✓ Bot V3 startup complete")
    logger.info("✓ API docs: http://localhost:8000/docs")
    logger.info("✓ WebSocket: ws://localhost:8000/v1/ws/dashboard")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """Graceful shutdown semua komponen."""
    logger.info("Shutting down Bot V3...")
    
    # Stop worker manager
    if _worker_manager:
        await _worker_manager.stop_all()
        logger.info("Worker manager stopped")
    
    # Stop connection pool
    if _connection_pool:
        await _connection_pool.stop()
        logger.info("Connection pool stopped")
    
    logger.info("Bot V3 shutdown complete")


# ============================================================================
# Health Check Endpoint
# ============================================================================

@app.get("/health")
async def root_health():
    """Simple health check (tanpa auth)."""
    return {
        "status": "healthy",
        "service": "Bot V3 Control Plane",
        "timestamp": datetime.utcnow().isoformat()
    }


# ============================================================================
# Dynamic Market Management
# ============================================================================

@app.post("/markets/add/{market}")
async def add_market(market: str):
    """Tambah market ke connection pool."""
    if _connection_pool is None:
        return {"error": "Connection pool not initialized"}
    
    def on_book(book: BookSnapshot):
        if _worker_manager:
            _worker_manager.route_book_event(book)
        asyncio.create_task(on_book_snapshot(book))
    
    _connection_pool.add_market_stream(
        market=market,
        on_book=on_book
    )
    
    logger.info(f"Added market stream: {market}")
    
    return {"message": f"Market {market} added", "market": market}


@app.post("/markets/start/{market}")
async def start_market_worker(
    market: str,
    guardrail_mode: str = "risk_free_only"
):
    """Start worker untuk market tertentu."""
    if _worker_manager is None:
        return {"error": "Worker manager not initialized"}
    
    from src.api.schemas import GuardrailMode
    
    mode = GuardrailMode(guardrail_mode)
    
    # Add worker jika belum ada
    if market not in _worker_manager._workers:
        _worker_manager.add_worker(
            market=market,
            guardrail_mode=mode,
            config_override=None
        )
    
    # Start worker
    await _worker_manager.start_worker(market)
    
    logger.info(f"Started worker for {market} with mode={mode.value}")
    
    return {
        "message": f"Worker started for {market}",
        "market": market,
        "guardrail_mode": mode.value
    }


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "src.main_v3:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
