"""
Market Worker untuk Bot V3.

Setiap market dijalankan oleh worker terpisah yang:
1. Menerima book snapshot dari WebSocket
2. Menjalankan guardrail check
3. Generate quote dari quote engine
4. Submit order ke exchange
5. Track fill & update inventory
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.infra.websocket_streams import BookSnapshot, FillEvent, OrderUpdate
from src.mm.guardrail import GuardrailMode, create_guardrail
from src.mm.quotes import QuoteEngine, QuoteRequest
from src.mm.pnl_formula import InventoryState

logger = logging.getLogger(__name__)


@dataclass
class MarketState:
    """State terkini untuk satu market."""
    market: str
    inventory: InventoryState = field(default_factory=InventoryState)
    last_book: Optional[BookSnapshot] = None
    last_fill_time: float = 0.0
    open_orders: Dict[str, Dict] = field(default_factory=dict)
    cycle_start_time: float = 0.0
    
    def time_in_cycle(self) -> float:
        """Waktu sejak cycle dimulai (detik)."""
        if self.cycle_start_time == 0:
            return 0.0
        return datetime.utcnow().timestamp() - self.cycle_start_time
    
    def reset_cycle(self):
        """Reset cycle timer."""
        self.cycle_start_time = datetime.utcnow().timestamp()


class MarketWorker:
    """
    Worker per market yang menjalankan loop event-driven.
    
    Alur:
    1. on_book() → Update book, generate quote, submit order
    2. on_fill() → Update inventory, adjust quote
    3. on_order_update() → Track status order
    """
    
    def __init__(
        self,
        market: str,
        guardrail_mode: GuardrailMode,
        config: Dict[str, Any],
        on_submit_order: Optional[callable] = None,
        on_cancel_order: Optional[callable] = None,
    ):
        self.market = market
        self.guardrail_mode = guardrail_mode
        self.config = config
        self.on_submit_order = on_submit_order
        self.on_cancel_order = on_cancel_order
        
        # Initialize components
        self.state = MarketState(market=market)
        self.guardrail = create_guardrail(mode=guardrail_mode, config=config)
        self.quote_engine = QuoteEngine(config=config)
        
        # State flags
        self._running = False
        self._order_queue: asyncio.Queue = asyncio.Queue()
        
        logger.info(f"[{market}] MarketWorker initialized with mode={guardrail_mode}")
    
    async def start(self):
        """Start worker loop."""
        self._running = True
        self.state.reset_cycle()
        
        logger.info(f"[{self.market}] MarketWorker started")
        
        # Process order queue
        while self._running:
            try:
                order_task = await asyncio.wait_for(
                    self._order_queue.get(),
                    timeout=1.0
                )
                await order_task
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.exception(f"[{self.market}] Error processing order: {e}")
    
    async def stop(self):
        """Stop worker dengan graceful shutdown."""
        self._running = False
        logger.info(f"[{self.market}] MarketWorker stopped")
    
    def on_book(self, book: BookSnapshot):
        """
        Callback saat book snapshot/update diterima.
        
        Alur:
        1. Update last_book
        2. Buat quote request
        3. Run guardrail check
        4. Generate quote
        5. Submit order (jika valid)
        """
        if not self._running:
            return
        
        try:
            self.state.last_book = book
            
            # Buat quote request
            time_in_cycle = self.state.time_in_cycle()
            request = QuoteRequest(
                market=self.market,
                book=book,
                inventory=self.state.inventory,
                time_in_cycle=time_in_cycle
            )
            
            # Guardrail check
            guardrail_result = self.guardrail.check(request)
            
            if not guardrail_result.allowed:
                logger.debug(
                    f"[{self.market}] Order blocked by guardrail: "
                    f"reason={guardrail_result.reason}"
                )
                # Cancel existing orders jika required
                if guardrail_result.cancel_required:
                    self._enqueue_cancel_all()
                return
            
            # Generate quote
            quote = self.quote_engine.generate_quote(request)
            
            if quote is None:
                logger.debug(f"[{self.market}] No quote generated (invalid params)")
                return
            
            # Submit order
            self._enqueue_submit_order(quote)
            
            logger.debug(
                f"[{self.market}] Quote generated: "
                f"bid={quote.bid_price}@{quote.bid_size}, "
                f"ask={quote.ask_price}@{quote.ask_size}"
            )
            
        except Exception as e:
            logger.exception(f"[{self.market}] Error in on_book: {e}")
    
    def on_fill(self, fill: FillEvent):
        """
        Callback saat fill diterima.
        
        Alur:
        1. Update inventory (size, avg price)
        2. Log fill
        3. Trigger re-quote (opsional, bisa langsung atau batch)
        """
        if fill.market != self.market:
            return
        
        try:
            # Update inventory
            self.state.inventory.apply_fill(fill)
            self.state.last_fill_time = datetime.utcnow().timestamp()
            
            logger.info(
                f"[{self.market}] Fill: {fill.side} {fill.size}@{fill.price}, "
                f"fee={fill.fee}{fill.fee_asset}, maker={fill.is_maker}"
            )
            
            # Trigger re-quote segera
            if self.state.last_book:
                self.on_book(self.state.last_book)
            
        except Exception as e:
            logger.exception(f"[{self.market}] Error in on_fill: {e}")
    
    def on_order_update(self, update: OrderUpdate):
        """
        Callback saat order update diterima.
        
        Alur:
        1. Update open_orders
        2. Jika FILLED/CANCELED, hapus dari tracking
        3. Log update
        """
        if update.market != self.market:
            return
        
        try:
            if update.status in ["FILLED", "CANCELED"]:
                if update.order_id in self.state.open_orders:
                    del self.state.open_orders[update.order_id]
                logger.info(
                    f"[{self.market}] Order {update.order_id} {update.status}"
                )
            else:
                self.state.open_orders[update.order_id] = {
                    "status": update.status,
                    "filled_size": update.filled_size,
                    "remaining_size": update.remaining_size,
                    "avg_price": update.avg_price,
                }
                logger.debug(
                    f"[{self.market}] Order {update.order_id} update: "
                    f"{update.status}, filled={update.filled_size}"
                )
            
        except Exception as e:
            logger.exception(f"[{self.market}] Error in on_order_update: {e}")
    
    def _enqueue_submit_order(self, quote):
        """Enqueue submit order task."""
        async def task():
            if self.on_submit_order:
                await self.on_submit_order(self.market, quote)
        
        self._order_queue.put_nowait(task())
    
    def _enqueue_cancel_all(self):
        """Enqueue cancel all orders task."""
        async def task():
            if self.on_cancel_order:
                await self.on_cancel_order(self.market)
        
        self._order_queue.put_nowait(task())


class WorkerManager:
    """
    Manager untuk multiple MarketWorkers.
    
    Fitur:
    - Start/stop workers per market
    - Routing event ke worker yang sesuai
    - Health check
    """
    
    def __init__(self, default_config: Dict[str, Any]):
        self.default_config = default_config
        self._workers: Dict[str, MarketWorker] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        
    def add_worker(
        self,
        market: str,
        guardrail_mode: GuardrailMode,
        config_override: Optional[Dict[str, Any]] = None,
        on_submit_order: Optional[callable] = None,
        on_cancel_order: Optional[callable] = None,
    ):
        """Tambah worker untuk market baru."""
        if market in self._workers:
            logger.warning(f"Worker for {market} already exists, skipping")
            return
        
        config = {**self.default_config, **(config_override or {})}
        
        worker = MarketWorker(
            market=market,
            guardrail_mode=guardrail_mode,
            config=config,
            on_submit_order=on_submit_order,
            on_cancel_order=on_cancel_order
        )
        
        self._workers[market] = worker
        logger.info(f"Added worker for {market} with mode={guardrail_mode}")
    
    async def start_worker(self, market: str):
        """Start worker untuk market tertentu."""
        if market not in self._workers:
            logger.error(f"Worker for {market} not found")
            return
        
        worker = self._workers[market]
        task = asyncio.create_task(worker.start(), name=f"worker-{market}")
        self._tasks[market] = task
        logger.info(f"Started worker for {market}")
    
    async def stop_worker(self, market: str):
        """Stop worker untuk market tertentu."""
        if market not in self._workers:
            return
        
        worker = self._workers[market]
        await worker.stop()
        
        if market in self._tasks:
            task = self._tasks[market]
            if not task.done():
                task.cancel()
            del self._tasks[market]
        
        logger.info(f"Stopped worker for {market}")
    
    async def start_all(self):
        """Start semua workers."""
        for market in self._workers:
            await self.start_worker(market)
    
    async def stop_all(self):
        """Stop semua workers."""
        for market in list(self._workers.keys()):
            await self.stop_worker(market)
    
    def route_book_event(self, book: BookSnapshot):
        """Route book event ke worker yang sesuai."""
        if book.market in self._workers:
            self._workers[book.market].on_book(book)
    
    def route_fill_event(self, fill: FillEvent):
        """Route fill event ke worker yang sesuai."""
        if fill.market in self._workers:
            self._workers[fill.market].on_fill(fill)
    
    def route_order_update(self, update: OrderUpdate):
        """Route order update ke worker yang sesuai."""
        if update.market in self._workers:
            self._workers[update.market].on_order_update(update)
    
    def get_worker(self, market: str) -> Optional[MarketWorker]:
        """Get worker untuk market tertentu."""
        return self._workers.get(market)
    
    def health_status(self) -> Dict[str, Any]:
        """Health status semua workers."""
        status = {}
        for market, worker in self._workers.items():
            task = self._tasks.get(market)
            status[market] = {
                "running": worker._running,
                "task_done": task.done() if task else None,
                "open_orders": len(worker.state.open_orders),
                "time_in_cycle": worker.state.time_in_cycle(),
            }
        return status


# Factory function
def create_worker_manager(config: Dict[str, Any]) -> WorkerManager:
    """Factory untuk membuat WorkerManager."""
    return WorkerManager(default_config=config)
