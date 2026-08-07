"""
Infrastruktur WebSocket untuk Bot V3.

Komponen:
- MarketStream: Langganan book (ticker, orderbook, trade) per market
- UserStream: Langganan fill & order update user
- ConnectionPool: Manajemen koneksi WebSocket dengan reconnect otomatis
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set

import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatusCode

logger = logging.getLogger(__name__)


@dataclass
class BookSnapshot:
    """Snapshot orderbook dari WebSocket."""
    market: str
    timestamp: float
    bids: List[List[float]]  # [[price, size], ...]
    asks: List[List[float]]
    sequence: int = 0


@dataclass
class FillEvent:
    """Event fill dari UserStream."""
    market: str
    side: str  # "BUY" atau "SELL"
    price: float
    size: float
    fee: float
    fee_asset: str
    order_id: str
    trade_id: str
    timestamp: float
    is_maker: bool


@dataclass
class OrderUpdate:
    """Update status order."""
    market: str
    order_id: str
    status: str  # NEW, FILLED, CANCELED, REJECTED
    filled_size: float
    remaining_size: float
    avg_price: Optional[float]
    timestamp: float


class MarketStream:
    """
    WebSocket client untuk market data (book, trade, ticker).
    
    Fitur:
    - Auto-reconnect dengan exponential backoff
    - Snapshot awal + incremental update
    - Callback per event type
    """
    
    def __init__(
        self,
        market: str,
        on_book: Optional[Callable[[BookSnapshot], None]] = None,
        on_trade: Optional[Callable[[Dict], None]] = None,
        on_ticker: Optional[Callable[[Dict], None]] = None,
        ws_url: str = "wss://ws.polymarket.com",
    ):
        self.market = market
        self.on_book = on_book
        self.on_trade = on_trade
        self.on_ticker = on_ticker
        self.ws_url = ws_url
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._reconnect_count = 0
        self._last_sequence = 0
        
    async def connect(self):
        """Mulai koneksi WebSocket dengan retry."""
        self._running = True
        
        while self._running:
            try:
                await self._connect_once()
            except (ConnectionClosed, InvalidStatusCode, OSError) as e:
                self._reconnect_count += 1
                delay = min(2 ** self._reconnect_count, 60)  # Max 60s
                logger.warning(
                    f"[{self.market}] WebSocket disconnected: {e}. "
                    f"Reconnecting in {delay}s (attempt {self._reconnect_count})..."
                )
                await asyncio.sleep(delay)
            except Exception as e:
                logger.exception(f"[{self.market}] Unexpected error: {e}")
                await asyncio.sleep(5)
    
    async def _connect_once(self):
        """Koneksi单次 dengan subscribe channels."""
        async with websockets.connect(self.ws_url) as ws:
            self._ws = ws
            self._reconnect_count = 0
            
            # Subscribe ke channels
            subscribe_msg = {
                "type": "subscribe",
                "markets": [self.market],
                "channels": ["book", "trade", "ticker"]
            }
            await ws.send(json.dumps(subscribe_msg))
            logger.info(f"[{self.market}] Subscribed to book, trade, ticker")
            
            # Loop receive messages
            async for message in ws:
                await self._handle_message(message)
    
    async def _handle_message(self, raw: str):
        """Parse dan dispatch message ke callback."""
        try:
            msg = json.loads(raw)
            msg_type = msg.get("type")
            
            if msg_type == "book_snapshot":
                snapshot = BookSnapshot(
                    market=msg["market"],
                    timestamp=msg["timestamp"],
                    bids=msg["bids"],
                    asks=msg["asks"],
                    sequence=msg.get("sequence", 0)
                )
                self._last_sequence = snapshot.sequence
                if self.on_book:
                    self.on_book(snapshot)
                    
            elif msg_type == "book_update":
                # Incremental update (implement merge logic di caller)
                snapshot = BookSnapshot(
                    market=msg["market"],
                    timestamp=msg["timestamp"],
                    bids=msg.get("bids", []),
                    asks=msg.get("asks", []),
                    sequence=msg.get("sequence", 0)
                )
                if self._last_sequence > 0 and snapshot.sequence <= self._last_sequence:
                    logger.debug(f"[{self.market}] Skip stale book update: {snapshot.sequence}")
                    return
                self._last_sequence = snapshot.sequence
                if self.on_book:
                    self.on_book(snapshot)
                    
            elif msg_type == "trade":
                if self.on_trade:
                    self.on_trade(msg)
                    
            elif msg_type == "ticker":
                if self.on_ticker:
                    self.on_ticker(msg)
                    
        except json.JSONDecodeError as e:
            logger.error(f"[{self.market}] Failed to parse message: {e}")
        except Exception as e:
            logger.exception(f"[{self.market}] Error handling message: {e}")
    
    async def stop(self):
        """Stop koneksi."""
        self._running = False
        if self._ws:
            await self._ws.close()
        logger.info(f"[{self.market}] MarketStream stopped")


class UserStream:
    """
    WebSocket client untuk user data (fill, order update).
    
    Fitur:
    - Autentikasi dengan API key
    - Auto-reconnect
    - Callback per fill & order update
    """
    
    def __init__(
        self,
        api_key: str,
        on_fill: Optional[Callable[[FillEvent], None]] = None,
        on_order_update: Optional[Callable[[OrderUpdate], None]] = None,
        ws_url: str = "wss://ws.polymarket.com/user",
    ):
        self.api_key = api_key
        self.on_fill = on_fill
        self.on_order_update = on_order_update
        self.ws_url = ws_url
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._reconnect_count = 0
        
    async def connect(self):
        """Mulai koneksi WebSocket dengan retry."""
        self._running = True
        
        while self._running:
            try:
                await self._connect_once()
            except (ConnectionClosed, InvalidStatusCode, OSError) as e:
                self._reconnect_count += 1
                delay = min(2 ** self._reconnect_count, 60)
                logger.warning(
                    f"UserStream disconnected: {e}. "
                    f"Reconnecting in {delay}s (attempt {self._reconnect_count})..."
                )
                await asyncio.sleep(delay)
            except Exception as e:
                logger.exception(f"UserStream unexpected error: {e}")
                await asyncio.sleep(5)
    
    async def _connect_once(self):
        """Koneksi单次 dengan autentikasi."""
        headers = {"X-API-Key": self.api_key}
        
        async with websockets.connect(self.ws_url, extra_headers=headers) as ws:
            self._ws = ws
            self._reconnect_count = 0
            
            # Subscribe ke fill & order events
            subscribe_msg = {
                "type": "subscribe",
                "channels": ["fill", "order_update"]
            }
            await ws.send(json.dumps(subscribe_msg))
            logger.info("UserStream subscribed to fill, order_update")
            
            # Loop receive messages
            async for message in ws:
                await self._handle_message(message)
    
    async def _handle_message(self, raw: str):
        """Parse dan dispatch message ke callback."""
        try:
            msg = json.loads(raw)
            event_type = msg.get("type")
            
            if event_type == "fill":
                fill = FillEvent(
                    market=msg["market"],
                    side=msg["side"],
                    price=float(msg["price"]),
                    size=float(msg["size"]),
                    fee=float(msg.get("fee", 0)),
                    fee_asset=msg.get("fee_asset", "USDC"),
                    order_id=msg["order_id"],
                    trade_id=msg["trade_id"],
                    timestamp=msg.get("timestamp", datetime.utcnow().timestamp()),
                    is_maker=msg.get("is_maker", False)
                )
                if self.on_fill:
                    self.on_fill(fill)
                    
            elif event_type == "order_update":
                update = OrderUpdate(
                    market=msg["market"],
                    order_id=msg["order_id"],
                    status=msg["status"],
                    filled_size=float(msg.get("filled_size", 0)),
                    remaining_size=float(msg.get("remaining_size", 0)),
                    avg_price=float(msg["avg_price"]) if msg.get("avg_price") else None,
                    timestamp=msg.get("timestamp", datetime.utcnow().timestamp())
                )
                if self.on_order_update:
                    self.on_order_update(update)
                    
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse user message: {e}")
        except Exception as e:
            logger.exception(f"Error handling user message: {e}")
    
    async def stop(self):
        """Stop koneksi."""
        self._running = False
        if self._ws:
            await self._ws.close()
        logger.info("UserStream stopped")


class ConnectionPool:
    """
    Pool manajemen koneksi WebSocket untuk multiple markets.
    
    Fitur:
    - Start/stop semua streams
    - Health check periodik
    - Graceful shutdown
    """
    
    def __init__(self):
        self._market_streams: Dict[str, MarketStream] = {}
        self._user_stream: Optional[UserStream] = None
        self._tasks: List[asyncio.Task] = []
        self._running = False
        
    def add_market_stream(
        self,
        market: str,
        on_book: Optional[Callable[[BookSnapshot], None]] = None,
        on_trade: Optional[Callable[[Dict], None]] = None,
        on_ticker: Optional[Callable[[Dict], None]] = None,
    ):
        """Tambah market stream ke pool."""
        if market in self._market_streams:
            logger.warning(f"Market {market} already in pool, skipping")
            return
        
        stream = MarketStream(
            market=market,
            on_book=on_book,
            on_trade=on_trade,
            on_ticker=on_ticker
        )
        self._market_streams[market] = stream
        logger.info(f"Added market stream: {market}")
    
    def set_user_stream(
        self,
        api_key: str,
        on_fill: Optional[Callable[[FillEvent], None]] = None,
        on_order_update: Optional[Callable[[OrderUpdate], None]] = None,
    ):
        """Set user stream."""
        self._user_stream = UserStream(
            api_key=api_key,
            on_fill=on_fill,
            on_order_update=on_order_update
        )
        logger.info("UserStream configured")
    
    async def start(self):
        """Start semua streams."""
        self._running = True
        
        # Start market streams
        for market, stream in self._market_streams.items():
            task = asyncio.create_task(stream.connect(), name=f"market-{market}")
            self._tasks.append(task)
            logger.info(f"Started market stream: {market}")
        
        # Start user stream
        if self._user_stream:
            task = asyncio.create_task(self._user_stream.connect(), name="user-stream")
            self._tasks.append(task)
            logger.info("Started user stream")
        
        logger.info(f"ConnectionPool started with {len(self._market_streams)} markets")
    
    async def stop(self):
        """Stop semua streams dengan graceful shutdown."""
        self._running = False
        
        # Stop all streams
        for market, stream in self._market_streams.items():
            await stream.stop()
        
        if self._user_stream:
            await self._user_stream.stop()
        
        # Cancel tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()
        
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        
        logger.info("ConnectionPool stopped")
    
    async def health_check(self, interval: int = 30):
        """Health check periodik (opsional)."""
        while self._running:
            await asyncio.sleep(interval)
            active_markets = len([s for s in self._market_streams.values() if s._ws is not None])
            user_active = self._user_stream is not None and self._user_stream._ws is not None
            logger.info(
                f"Health check: {active_markets}/{len(self._market_streams)} markets, "
                f"user_stream={user_active}"
            )


# Factory function
def create_connection_pool() -> ConnectionPool:
    """Factory untuk membuat ConnectionPool."""
    return ConnectionPool()
