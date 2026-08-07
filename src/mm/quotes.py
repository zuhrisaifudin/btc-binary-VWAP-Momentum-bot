"""
src/mm/quotes.py — Quote engine untuk Bot V3

Menghitung harga bid berdasarkan:
1. Book in-memory (dari market_stream)
2. Profil waktu (taker/maker berdasarkan secs_to_expiry)
3. Cap dinamis dari rumus (Pu+Pd < 1)
4. Sizing dari saldo tersisa
"""

from dataclasses import dataclass, field
from typing import Optional, List, Tuple, TYPE_CHECKING
from enum import Enum

if TYPE_CHECKING:
    from src.mm.pnl_formula import InventoryState


class ExecutionPhase(str, Enum):
    """Fase eksekusi berdasarkan waktu ke expiry."""
    OPEN_TAKER = "open_taker"         # t > 295s: seed posisi dengan taker
    GRID_MAKER = "grid_maker"         # 60s < t <= 295s: maker-dominan
    MAKER_ONLY = "maker_only"         # t <= 60s: hanya maker
    TAPER = "taper"                   # t <= 15s: size mengecil


@dataclass(frozen=True)
class QuoteConfig:
    """Konfigurasi quote engine."""
    # Waktu fase
    taker_until_s: float = 295.0
    maker_only_below_s: float = 60.0
    taper_size_below_s: float = 15.0
    
    # Agresivitas
    taker_open_max: float = 0.56  # Peluang taker maksimum saat buka
    
    # Spread & tick
    spread_bps: float = 0.02      # Spread target (2%)
    pair_margin: float = 0.02     # Margin aman Pu+Pd < 1
    
    # Size
    min_shares: float = 1.0
    max_order_usd: float = 2.50


@dataclass
class BookLevel:
    """Satu level order book."""
    price: float
    size: float


@dataclass
class OrderBook:
    """Order book in-memory untuk satu market."""
    condition_id: str
    bids_up: List[BookLevel]   # Sorted descending (highest first)
    asks_up: List[BookLevel]   # Sorted ascending (lowest first)
    bids_down: List[BookLevel]
    asks_down: List[BookLevel]
    
    def mid_price(self, side: str) -> Optional[float]:
        """Harga tengah untuk sisi tertentu."""
        if side == "UP":
            if not self.bids_up or not self.asks_up:
                return None
            return (self.bids_up[0].price + self.asks_up[0].price) / 2
        elif side == "DOWN":
            if not self.bids_down or not self.asks_down:
                return None
            return (self.bids_down[0].price + self.asks_down[0].price) / 2
        return None
    
    def best_bid(self, side: str) -> Optional[float]:
        """Bid terbaik (tertinggi) untuk sisi tertentu."""
        if side == "UP" and self.bids_up:
            return self.bids_up[0].price
        elif side == "DOWN" and self.bids_down:
            return self.bids_down[0].price
        return None
    
    def best_ask(self, side: str) -> Optional[float]:
        """Ask terbaik (terendah) untuk sisi tertentu."""
        if side == "UP" and self.asks_up:
            return self.asks_up[0].price
        elif side == "DOWN" and self.asks_down:
            return self.asks_down[0].price
        return None


@dataclass(frozen=True)
class QuoteRequest:
    """Request untuk generate quote."""
    market: str
    book: 'OrderBook'
    inventory: 'InventoryState'
    time_in_cycle: float
    available_balance: float = 0.0
    open_orders_notional: float = 0.0


@dataclass(frozen=True)
class Quote:
    """Hasil quote untuk satu sisi."""
    side: str
    price: float
    size: float
    is_taker: bool
    phase: ExecutionPhase
    reason: str


class QuoteEngine:
    """
    Quote engine Bot V3.
    
    Menghasilkan quote berdasarkan:
    1. Fase waktu (taker/maker)
    2. Book in-memory
    3. Cap rumus (Pu+Pd < 1)
    4. Saldo tersedia
    """
    
    def __init__(self, cfg: QuoteConfig):
        self.cfg = cfg
    
    def get_phase(self, secs_to_expiry: float) -> ExecutionPhase:
        """Tentukan fase eksekusi berdasarkan waktu ke expiry."""
        if secs_to_expiry > self.cfg.taker_until_s:
            return ExecutionPhase.OPEN_TAKER
        elif secs_to_expiry <= self.cfg.taper_size_below_s:
            return ExecutionPhase.TAPER
        elif secs_to_expiry <= self.cfg.maker_only_below_s:
            return ExecutionPhase.MAKER_ONLY
        else:
            return ExecutionPhase.GRID_MAKER
    
    def should_be_taker(
        self,
        phase: ExecutionPhase,
        secs_to_expiry: float
    ) -> bool:
        """
        Putuskan apakah harus jadi taker (menyeberang spread).
        
        Menggunakan kurva agresivitas menurun terhadap waktu.
        """
        if phase == ExecutionPhase.MAKER_ONLY or phase == ExecutionPhase.TAPER:
            return False
        
        if phase == ExecutionPhase.OPEN_TAKER:
            # Saat buka, agresif tinggi
            return True
        
        # GRID_MAKER: kurva menurun
        # p_agresif(t) ≈ clamp((t - maker_only_below) / (taker_until - maker_only_below), 0, taker_open_max)
        t = secs_to_expiry
        t_min = self.cfg.maker_only_below_s
        t_max = self.cfg.taker_until_s
        
        if t <= t_min:
            return False
        
        probability = (t - t_min) / (t_max - t_min)
        probability = min(probability, self.cfg.taker_open_max)
        
        # Untuk deterministik demo, pakai threshold
        # Di production, bisa pakai random.random() < probability
        return probability > 0.5
    
    def calculate_price_cap(
        self,
        side: str,
        inv_pu: float,
        inv_pd: float
    ) -> float:
        """
        Hitung cap harga dari rumus Pu+Pd < 1.
        
        p_bid_UP_max = 1 - Pd - margin
        p_bid_DOWN_max = 1 - Pu - margin
        """
        if side == "UP":
            return 1.0 - inv_pd - self.cfg.pair_margin
        elif side == "DOWN":
            return 1.0 - inv_pu - self.cfg.pair_margin
        return 0.0
    
    def calculate_size_from_balance(
        self,
        price: float,
        available_balance: float,
        total_open_orders_notional: float
    ) -> float:
        """
        Hitung size berdasarkan saldo tersedia.
        
        budget_live = min(budget_sim, saldo_venue - open_orders_notional)
        size = budget / price
        """
        effective_balance = max(0, available_balance - total_open_orders_notional)
        if price <= 0:
            return 0.0
        
        size = effective_balance / price
        return max(size, 0)
    
    def generate_quote(
        self,
        request: QuoteRequest
    ) -> Optional[Quote]:
        """
        Generate quote untuk satu sisi.
        
        Args:
            request: QuoteRequest dengan book, inventory, waktu
        
        Returns:
            Quote atau None jika tidak boleh order
        """
        # Extract dari request
        book = request.book
        side = "UP"  # Default, bisa dikembangkan untuk multi-side
        secs_to_expiry = request.time_in_cycle
        inv_su = request.inventory.su
        inv_sd = request.inventory.sd
        inv_cost_u = request.inventory.cost_u
        inv_cost_d = request.inventory.cost_d
        available_balance = request.available_balance
        open_orders_notional = request.open_orders_notional
        
        # 1. Tentukan fase
        phase = self.get_phase(secs_to_expiry)
        
        # 2. Cek apakah boleh taker
        is_taker = self.should_be_taker(phase, secs_to_expiry)
        
        # 3. Dapatkan harga dari book
        if is_taker:
            # Taker: ambil ask (seberang spread)
            base_price = book.best_ask(side)
            if base_price is None:
                return None
        else:
            # Maker: pasang di bid (atau sedikit di atas best bid)
            base_price = book.best_bid(side)
            if base_price is None:
                # Book kosong, pakai mid
                base_price = book.mid_price(side)
                if base_price is None:
                    return None
                # Maker: taruh sedikit di bawah mid
                base_price = base_price * (1 - self.cfg.spread_bps / 2)
        
        # Hitung implied prices
        inv_pu = inv_cost_u / inv_su if inv_su > 0 else 0.0
        inv_pd = inv_cost_d / inv_sd if inv_sd > 0 else 0.0
        
        # 4. Apply cap rumus (Pu+Pd < 1)
        price_cap = self.calculate_price_cap(side, inv_pu, inv_pd)
        price = min(base_price, price_cap)
        
        # Jika price <= 0 setelah cap, skip
        if price <= 0:
            return None
        
        # 5. Hitung size dari saldo
        size = self.calculate_size_from_balance(
            price, available_balance, open_orders_notional
        )
        
        # 6. Apply batas min/max
        if size < self.cfg.min_shares:
            return None
        
        # Taper: kecilkan size di detik akhir
        if phase == ExecutionPhase.TAPER:
            taper_factor = secs_to_expiry / self.cfg.taper_size_below_s
            size = size * taper_factor
        
        # Batas max order USD
        max_shares_by_usd = self.cfg.max_order_usd / price
        size = min(size, max_shares_by_usd)
        
        if size < self.cfg.min_shares:
            return None
        
        return Quote(
            side=side,
            price=round(price, 4),
            size=round(size, 2),
            is_taker=is_taker,
            phase=phase,
            reason=f"{phase.value}, {'taker' if is_taker else 'maker'}",
        )
    
    def generate_quotes_two_sided_from_request(
        self,
        request: 'QuoteRequest'
    ) -> Tuple[Optional['Quote'], Optional['Quote']]:
        """
        Generate quote untuk kedua sisi (UP dan DOWN) dari QuoteRequest.
        
        Returns:
            (quote_up, quote_down)
        """
        # Generate quote UP
        up_request = QuoteRequest(
            market=request.market,
            book=request.book,
            inventory=request.inventory,
            time_in_cycle=request.time_in_cycle,
            available_balance=request.available_balance,
            open_orders_notional=request.open_orders_notional
        )
        quote_up = self.generate_quote(up_request)
        
        # Generate quote DOWN (butuh side parameter, akan dihandle di generate_quote)
        down_request = QuoteRequest(
            market=request.market,
            book=request.book,
            inventory=request.inventory,
            time_in_cycle=request.time_in_cycle,
            available_balance=request.available_balance,
            open_orders_notional=request.open_orders_notional
        )
        quote_down = self._generate_quote_for_side(down_request, "DOWN")
        
        return quote_up, quote_down
    
    def _generate_quote_for_side(
        self,
        request: 'QuoteRequest',
        side: str
    ) -> Optional['Quote']:
        """Internal method untuk generate quote dengan side tertentu."""
        # Extract dari request
        book = request.book
        secs_to_expiry = request.time_in_cycle
        inv_su = request.inventory.su
        inv_sd = request.inventory.sd
        inv_cost_u = request.inventory.cost_u
        inv_cost_d = request.inventory.cost_d
        available_balance = request.available_balance
        open_orders_notional = request.open_orders_notional
        
        # 1. Tentukan fase
        phase = self.get_phase(secs_to_expiry)
        
        # 2. Cek apakah boleh taker
        is_taker = self.should_be_taker(phase, secs_to_expiry)
        
        # 3. Dapatkan harga dari book
        if is_taker:
            # Taker: ambil ask (seberang spread)
            base_price = book.best_ask(side)
            if base_price is None:
                return None
        else:
            # Maker: pasang di bid (atau sedikit di atas best bid)
            base_price = book.best_bid(side)
            if base_price is None:
                # Book kosong, pakai mid
                base_price = book.mid_price(side)
                if base_price is None:
                    return None
                # Maker: taruh sedikit di bawah mid
                base_price = base_price * (1 - self.cfg.spread_bps / 2)
        
        # Hitung implied prices
        inv_pu = inv_cost_u / inv_su if inv_su > 0 else 0.0
        inv_pd = inv_cost_d / inv_sd if inv_sd > 0 else 0.0
        
        # 4. Apply cap rumus (Pu+Pd < 1)
        price_cap = self.calculate_price_cap(side, inv_pu, inv_pd)
        price = min(base_price, price_cap)
        
        # Jika price <= 0 setelah cap, skip
        if price <= 0:
            return None
        
        # 5. Hitung size dari saldo
        size = self.calculate_size_from_balance(
            price, available_balance, open_orders_notional
        )
        
        # 6. Apply batas min/max
        if size < self.cfg.min_shares:
            return None
        
        # Taper: kecilkan size di detik akhir
        if phase == ExecutionPhase.TAPER:
            taper_factor = secs_to_expiry / self.cfg.taper_size_below_s
            size = size * taper_factor
        
        # Batas max order USD
        max_shares_by_usd = self.cfg.max_order_usd / price
        size = min(size, max_shares_by_usd)
        
        if size < self.cfg.min_shares:
            return None
        
        return Quote(
            side=side,
            price=round(price, 4),
            size=round(size, 2),
            is_taker=is_taker,
            phase=phase,
            reason=f"{phase.value}, {'taker' if is_taker else 'maker'}",
        )
    
    def generate_quotes_two_sided(
        self,
        book: OrderBook,
        secs_to_expiry: float,
        inv_su: float,
        inv_sd: float,
        inv_cost_u: float,
        inv_cost_d: float,
        available_balance: float,
        open_orders_notional: float = 0.0
    ) -> Tuple[Optional[Quote], Optional[Quote]]:
        """
        Generate quote untuk kedua sisi (UP dan DOWN) - legacy interface.
        
        Returns:
            (quote_up, quote_down)
        """
        # Buat QuoteRequest dari parameter
        from src.mm.pnl_formula import InventoryState
        
        inventory = InventoryState(
            su=inv_su,
            sd=inv_sd,
            cost_u=inv_cost_u,
            cost_d=inv_cost_d
        )
        
        request = QuoteRequest(
            market="unknown",
            book=book,
            inventory=inventory,
            time_in_cycle=secs_to_expiry,
            available_balance=available_balance,
            open_orders_notional=open_orders_notional
        )
        
        return self.generate_quotes_two_sided_from_request(request)
