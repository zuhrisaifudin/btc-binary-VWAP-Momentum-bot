"""
Dual-Side Scaling & Regime Adaptation Trading Bot
Strategi untuk Polymarket Binary Options (5-minute cycles)

Komponen Utama:
1. Regime Detection (Hurst Exponent + Order Flow Imbalance)
2. Modified Kelly Criterion for Position Sizing
3. Smart Scaling-In Execution Algorithm
4. Maker Fee Optimization
"""

import numpy as np
from typing import Tuple, Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
import warnings


class MarketRegime(Enum):
    TRENDING = "trending"
    MEAN_REVERTING = "mean_reverting"
    NEUTRAL = "neutral"


class PositionSide(Enum):
    UP = "up"
    DOWN = "down"


@dataclass
class OrderBookSnapshot:
    """Snapshot order book untuk menghitung OFI"""
    bids: List[Tuple[float, float]]  # [(price, size), ...]
    asks: List[Tuple[float, float]]  # [(price, size), ...]
    timestamp: float


@dataclass
class TradeConfig:
    """Konfigurasi trading parameters"""
    total_capital: float = 1000.0  # Total modal per siklus
    kelly_fraction: float = 0.5    # Half-Kelly untuk reduksi volatilitas
    dominant_ratio: float = 0.75   # 75% untuk posisi dominan
    insurance_ratio: float = 0.25  # 25% untuk posisi asuransi
    num_scale_parts: int = 8       # Jumlah bagian untuk scaling-in
    scale_duration_sec: int = 120  # Durasi scaling-in (detik)
    min_prob_edge: float = 0.05    # Minimal edge probabilitas untuk entry
    max_position_size: float = 500.0  # Maksimal posisi per sisi


class HurstExponentCalculator:
    """
    Menghitung Hurst Exponent menggunakan Rescaled Range Analysis (R/S)
    H > 0.5: Trending (persistent)
    H < 0.5: Mean Reverting (anti-persistent)
    H = 0.5: Random Walk
    """
    
    def __init__(self, min_lag: int = 2, max_lag: int = 20):
        self.min_lag = min_lag
        self.max_lag = max_lag
    
    def calculate(self, prices: np.ndarray) -> float:
        """
        Hitung Hurst Exponent dari series harga
        
        Args:
            prices: Array harga tick-level atau 1-menit
            
        Returns:
            Hurst Exponent value
        """
        if len(prices) < self.max_lag * 2:
            warnings.warn("Data terlalu pendek untuk perhitungan Hurst yang akurat")
            return 0.5
        
        # Hitung returns logaritmik
        log_returns = np.log(prices[1:] / prices[:-1])
        
        # Hitung R/S untuk berbagai lag
        lags = range(self.min_lag, min(self.max_lag, len(log_returns) // 2))
        rs_values = []
        
        for lag in lags:
            rs = self._rescaled_range(log_returns, lag)
            if rs > 0:
                rs_values.append((lag, rs))
        
        if len(rs_values) < 3:
            return 0.5
        
        # Regresi log-log untuk mendapatkan H
        log_lags = np.log([x[0] for x in rs_values])
        log_rs = np.log([x[1] for x in rs_values])
        
        # Fit linear regression: log(R/S) = H * log(lag) + c
        coefficients = np.polyfit(log_lags, log_rs, 1)
        hurst = coefficients[0]
        
        return np.clip(hurst, 0.0, 1.0)
    
    def _rescaled_range(self, returns: np.ndarray, lag: int) -> float:
        """Hitung R/S statistic untuk lag tertentu"""
        n_chunks = len(returns) // lag
        
        if n_chunks == 0:
            return 0.0
        
        rs_values = []
        
        for i in range(n_chunks):
            chunk = returns[i * lag:(i + 1) * lag]
            
            # Cumulative deviations from mean
            mean_return = np.mean(chunk)
            cumulative_deviations = np.cumsum(chunk - mean_return)
            
            # Range (R)
            R = np.max(cumulative_deviations) - np.min(cumulative_deviations)
            
            # Standard deviation (S)
            S = np.std(chunk)
            
            if S > 0:
                rs_values.append(R / S)
        
        return np.mean(rs_values) if rs_values else 0.0


class OrderFlowImbalanceCalculator:
    """
    Menghitung Order Flow Imbalance (OFI) dari order book
    OFI positif = tekanan beli kuat
    OFI negatif = tekanan jual kuat
    """
    
    def __init__(self, depth_levels: int = 5):
        self.depth_levels = depth_levels
    
    def calculate(self, order_book: OrderBookSnapshot) -> float:
        """
        Hitung OFI dari snapshot order book
        
        Args:
            order_book: Snapshot order book terkini
            
        Returns:
            OFI value (normalized between -1 and 1)
        """
        if not order_book.bids or not order_book.asks:
            return 0.0
        
        # Ambil top N levels
        top_bids = order_book.bids[:self.depth_levels]
        top_asks = order_book.asks[:self.depth_levels]
        
        # Hitung volume-weighted imbalance
        bid_volume = sum(size * (1.0 / (i + 1)) for i, (_, size) in enumerate(top_bids))
        ask_volume = sum(size * (1.0 / (i + 1)) for i, (_, size) in enumerate(top_asks))
        
        total_volume = bid_volume + ask_volume
        
        if total_volume == 0:
            return 0.0
        
        # Normalized OFI: (bid_volume - ask_volume) / total_volume
        ofi = (bid_volume - ask_volume) / total_volume
        
        return np.clip(ofi, -1.0, 1.0)


class RegimeDetector:
    """
    Deteksi regime pasar menggunakan kombinasi Hurst Exponent dan OFI
    """
    
    def __init__(self):
        self.hurst_calculator = HurstExponentCalculator()
        self.ofi_calculator = OrderFlowImbalanceCalculator()
        
        # Thresholds
        self.hurst_trending_threshold = 0.55
        self.hurst_reverting_threshold = 0.45
        self.ofi_strong_threshold = 0.3
    
    def detect_regime(self, prices: np.ndarray, order_book: OrderBookSnapshot) -> Tuple[MarketRegime, str]:
        """
        Deteksi regime pasar dan arah dominan
        
        Args:
            prices: Array harga historis
            order_book: Snapshot order book terkini
            
        Returns:
            Tuple (MarketRegime, dominant_side)
        """
        # Hitung Hurst Exponent
        hurst = self.hurst_calculator.calculate(prices)
        
        # Hitung OFI
        ofi = self.ofi_calculator.calculate(order_book)
        
        # Tentukan regime
        if hurst > self.hurst_trending_threshold:
            regime = MarketRegime.TRENDING
            # Dalam trending, ikuti arah OFI
            if ofi > self.ofi_strong_threshold:
                dominant_side = PositionSide.UP
            elif ofi < -self.ofi_strong_threshold:
                dominant_side = PositionSide.DOWN
            else:
                # Jika OFI netral, lihat momentum harga terakhir
                if len(prices) >= 10:
                    recent_momentum = prices[-1] - prices[-5]
                    dominant_side = PositionSide.UP if recent_momentum > 0 else PositionSide.DOWN
                else:
                    dominant_side = PositionSide.UP if ofi > 0 else PositionSide.DOWN
                    
        elif hurst < self.hurst_reverting_threshold:
            regime = MarketRegime.MEAN_REVERTING
            # Dalam mean reverting, lawan arah pergerakan terakhir
            if len(prices) >= 10:
                recent_momentum = prices[-1] - prices[-5]
                dominant_side = PositionSide.DOWN if recent_momentum > 0 else PositionSide.UP
            else:
                # Jika tidak ada data cukup, gunakan OFI terbalik
                dominant_side = PositionSide.DOWN if ofi > 0 else PositionSide.UP
        else:
            regime = MarketRegime.NEUTRAL
            # Dalam regime netral, gunakan OFI sebagai panduan utama
            dominant_side = PositionSide.UP if ofi > 0 else PositionSide.DOWN
        
        return regime, dominant_side.value


class KellyCriterionCalculator:
    """
    Modified Kelly Criterion untuk binary options Polymarket
    
    Rumus: f* = [p(1-P) - (1-p)P] / [P(1-P)]
    Dimana:
      p = probabilitas kemenangan (dari model bot)
      P = harga pasar saat ini (implies probability)
    """
    
    def __init__(self, config: TradeConfig):
        self.config = config
    
    def calculate_position_sizes(
        self,
        true_probability: float,
        market_price: float,
        dominant_side: str
    ) -> Dict[str, float]:
        """
        Hitung ukuran posisi untuk sisi dominan dan asuransi
        
        Args:
            true_probability: Probabilitas kemenangan menurut model bot (0-1)
            market_price: Harga pasar saat ini (0-1)
            dominant_side: Sisi dominan ('up' atau 'down')
            
        Returns:
            Dictionary dengan ukuran posisi untuk setiap sisi
        """
        # Validasi input
        if not 0 < market_price < 1:
            raise ValueError("Market price harus antara 0 dan 1")
        if not 0 <= true_probability <= 1:
            raise ValueError("True probability harus antara 0 dan 1")
        
        # Hitung Kelly fraction penuh
        P = market_price
        p = true_probability
        
        # Kelly formula untuk binary options
        numerator = p * (1 - P) - (1 - p) * P
        denominator = P * (1 - P)
        
        if denominator == 0:
            kelly_fraction = 0.0
        else:
            kelly_fraction = numerator / denominator
        
        # Apply half-Kelly untuk reduksi volatilitas
        kelly_fraction *= self.config.kelly_fraction
        
        # Pastikan tidak negatif
        kelly_fraction = max(0.0, kelly_fraction)
        
        # Hitung ukuran posisi total berdasarkan Kelly
        total_kelly_size = min(
            kelly_fraction * self.config.total_capital,
            self.config.max_position_size
        )
        
        # Alokasi ke posisi dominan dan asuransi
        dominant_size = total_kelly_size * self.config.dominant_ratio
        insurance_size = total_kelly_size * self.config.insurance_ratio
        
        # Tentukan alokasi berdasarkan sisi dominan
        if dominant_side == 'up':
            up_size = dominant_size
            down_size = insurance_size
        else:
            up_size = insurance_size
            down_size = dominant_size
        
        return {
            'up': up_size,
            'down': down_size,
            'total': up_size + down_size,
            'kelly_fraction': kelly_fraction,
            'edge': abs(p - P)  # Edge probabilitas
        }
    
    def should_enter_trade(self, true_probability: float, market_price: float) -> bool:
        """
        Tentukan apakah harus entry berdasarkan minimal edge
        
        Args:
            true_probability: Probabilitas kemenangan menurut model
            market_price: Harga pasar saat ini
            
        Returns:
            True jika sebaiknya entry
        """
        edge = abs(true_probability - market_price)
        return edge >= self.config.min_prob_edge


class ScalingExecutionEngine:
    """
    Smart Scaling-In Execution Algorithm
    Membagi eksekusi menjadi beberapa bagian kecil untuk mengurangi slippage
    """
    
    def __init__(self, config: TradeConfig):
        self.config = config
        self.orders_placed = []
    
    def generate_scaling_orders(
        self,
        side: str,
        total_size: float,
        current_market_price: float,
        order_book: OrderBookSnapshot
    ) -> List[Dict]:
        """
        Generate daftar limit orders untuk scaling-in
        
        Args:
            side: 'up' atau 'down'
            total_size: Total ukuran posisi yang diinginkan
            current_market_price: Harga pasar saat ini
            order_book: Snapshot order book terkini
            
        Returns:
            List of order dictionaries dengan price, size, timing
        """
        if total_size <= 0:
            return []
        
        num_parts = self.config.num_scale_parts
        size_per_part = total_size / num_parts
        interval_seconds = self.config.scale_duration_sec / num_parts
        
        orders = []
        
        # Tentukan offset harga untuk limit orders
        # Untuk sisi UP: place limit order di bawah market (bid side)
        # Untuk sisi DOWN: place limit order di atas market (ask side)
        if side == 'up':
            # Place pada bid side atau sedikit di atas best bid
            if order_book.bids:
                best_bid = order_book.bids[0][0]
                base_price = best_bid
            else:
                base_price = current_market_price * 0.995
            
            price_offset = -0.002  # 0.2% di bawah market
            
        else:  # down
            # Place pada ask side atau sedikit di bawah best ask
            if order_book.asks:
                best_ask = order_book.asks[0][0]
                base_price = best_ask
            else:
                base_price = current_market_price * 1.005
            
            price_offset = 0.002  # 0.2% di atas market
        
        # Generate orders dengan dynamic pricing
        for i in range(num_parts):
            # Time scheduling
            execution_time = i * interval_seconds
            
            # Price adjustment: geser sedikit jika harga bergerak
            # Ini adalah simplified version; production code perlu real-time adjustment
            dynamic_offset = price_offset * (1 + 0.1 * (i / num_parts))
            
            if side == 'up':
                limit_price = min(base_price + dynamic_offset, current_market_price)
            else:
                limit_price = max(base_price - dynamic_offset, current_market_price)
            
            # Pastikan price dalam bounds yang wajar
            limit_price = np.clip(limit_price, 0.01, 0.99)
            
            order = {
                'side': side,
                'size': size_per_part,
                'limit_price': round(limit_price, 4),
                'execution_delay_sec': execution_time,
                'order_type': 'limit',
                'maker_order': True  # Selalu maker untuk avoid fees
            }
            
            orders.append(order)
        
        return orders
    
    def optimize_for_maker_fee(self, orders: List[Dict], order_book: OrderBookSnapshot) -> List[Dict]:
        """
        Optimasi penempatan limit order untuk memastikan maker status
        
        Args:
            orders: List orders yang akan dioptimasi
            order_book: Snapshot order book terkini
            
        Returns:
            List orders yang dioptimasi
        """
        optimized_orders = []
        
        for order in orders:
            optimized_order = order.copy()
            
            if order['side'] == 'up':
                # Untuk beli UP, place di bid side
                if order_book.bids:
                    best_bid = order_book.bids[0][0]
                    # Place slightly above best bid untuk priority, tapi tetap maker
                    optimized_order['limit_price'] = min(
                        best_bid + 0.001,
                        order['limit_price']
                    )
            else:
                # Untuk beli DOWN, place di ask side
                if order_book.asks:
                    best_ask = order_book.asks[0][0]
                    # Place slightly below best ask untuk priority, tapi tetap maker
                    optimized_order['limit_price'] = max(
                        best_ask - 0.001,
                        order['limit_price']
                    )
            
            optimized_orders.append(optimized_order)
        
        return optimized_orders


class DualSideScalingBot:
    """
    Main bot class yang mengintegrasikan semua komponen
    """
    
    def __init__(self, config: TradeConfig):
        self.config = config
        self.regime_detector = RegimeDetector()
        self.kelly_calculator = KellyCriterionCalculator(config)
        self.execution_engine = ScalingExecutionEngine(config)
        
        # State
        self.current_positions = {'up': 0.0, 'down': 0.0}
        self.is_active = False
    
    def analyze_and_prepare_trades(
        self,
        prices: np.ndarray,
        order_book: OrderBookSnapshot,
        model_probability: float
    ) -> Dict:
        """
        Analisis pasar dan siapkan rencana trading
        
        Args:
            prices: Array harga historis (tick-level atau 1-min)
            order_book: Snapshot order book terkini
            model_probability: Probabilitas kemenangan dari model ML/statistical
            
        Returns:
            Trading plan dictionary
        """
        # 1. Deteksi regime dan arah dominan
        regime, dominant_side = self.regime_detector.detect_regime(prices, order_book)
        
        # 2. Dapatkan harga pasar saat ini
        if order_book.bids and order_book.asks:
            mid_price = (order_book.bids[0][0] + order_book.asks[0][0]) / 2
        else:
            mid_price = prices[-1] if len(prices) > 0 else 0.5
        
        # 3. Cek apakah sebaiknya entry
        should_enter = self.kelly_calculator.should_enter_trade(
            model_probability,
            mid_price if dominant_side == 'up' else (1 - mid_price)
        )
        
        if not should_enter:
            return {
                'action': 'no_trade',
                'reason': 'Insufficient edge',
                'regime': regime.value,
                'dominant_side': dominant_side,
                'model_prob': model_probability,
                'market_price': mid_price,
                'edge': abs(model_probability - mid_price)
            }
        
        # 4. Hitung ukuran posisi menggunakan Kelly
        position_sizes = self.kelly_calculator.calculate_position_sizes(
            model_probability,
            mid_price,
            dominant_side
        )
        
        # 5. Generate scaling orders untuk kedua sisi
        up_orders = []
        down_orders = []
        
        if position_sizes['up'] > 0:
            up_orders = self.execution_engine.generate_scaling_orders(
                side='up',
                total_size=position_sizes['up'],
                current_market_price=mid_price,
                order_book=order_book
            )
            up_orders = self.execution_engine.optimize_for_maker_fee(up_orders, order_book)
        
        if position_sizes['down'] > 0:
            down_orders = self.execution_engine.generate_scaling_orders(
                side='down',
                total_size=position_sizes['down'],
                current_market_price=mid_price,
                order_book=order_book
            )
            down_orders = self.execution_engine.optimize_for_maker_fee(down_orders, order_book)
        
        return {
            'action': 'execute',
            'regime': regime.value,
            'dominant_side': dominant_side,
            'market_price': mid_price,
            'model_probability': model_probability,
            'position_sizes': position_sizes,
            'up_orders': up_orders,
            'down_orders': down_orders,
            'total_orders': len(up_orders) + len(down_orders),
            'estimated_duration_sec': self.config.scale_duration_sec
        }
    
    def execute_trading_cycle(
        self,
        prices: np.ndarray,
        order_book: OrderBookSnapshot,
        model_probability: float
    ) -> Dict:
        """
        Execute satu siklus trading lengkap
        
        Args:
            prices: Array harga historis
            order_book: Snapshot order book
            model_probability: Probabilitas dari model
            
        Returns:
            Execution result
        """
        # Analisis dan siapkan trades
        trading_plan = self.analyze_and_prepare_trades(
            prices, order_book, model_probability
        )
        
        if trading_plan['action'] == 'no_trade':
            return trading_plan
        
        # Simulasi eksekusi (dalam production, ini akan call API Polymarket)
        executed_orders = []
        
        # Eksekusi orders secara berurutan (simulasi)
        all_orders = trading_plan['up_orders'] + trading_plan['down_orders']
        
        for order in all_orders:
            # Dalam production:
            # 1. Wait untuk execution_delay_sec
            # 2. Place limit order via Polymarket API
            # 3. Monitor order status
            # 4. Adjust jika perlu
            
            executed_order = {
                **order,
                'status': 'placed',
                'timestamp': None  # Akan diisi saat eksekusi nyata
            }
            executed_orders.append(executed_order)
        
        self.is_active = True
        
        return {
            **trading_plan,
            'executed_orders': executed_orders,
            'execution_status': 'active'
        }


# ============================================================================
# CONTOH PENGGUNAAN DAN SIMULASI
# ============================================================================

def example_usage():
    """Contoh penggunaan bot dengan data simulasi"""
    
    # Setup konfigurasi
    config = TradeConfig(
        total_capital=1000.0,
        kelly_fraction=0.5,
        dominant_ratio=0.75,
        insurance_ratio=0.25,
        num_scale_parts=8,
        scale_duration_sec=120
    )
    
    # Inisialisasi bot
    bot = DualSideScalingBot(config)
    
    # Simulasi data harga (trending upward)
    np.random.seed(42)
    base_price = 0.60
    trend = np.linspace(0, 0.05, 100)
    noise = np.random.normal(0, 0.005, 100)
    prices = base_price + trend + noise
    
    # Simulasi order book
    order_book = OrderBookSnapshot(
        bids=[(0.598, 150), (0.597, 200), (0.596, 180)],
        asks=[(0.602, 140), (0.603, 190), (0.604, 170)],
        timestamp=1234567890.0
    )
    
    # Model probability (bot menilai UP memiliki 65% chance)
    model_prob = 0.65
    
    print("=" * 80)
    print("DUAL-SIDE SCALING & REGIME ADAPTATION BOT - SIMULASI")
    print("=" * 80)
    
    # Jalankan analisis
    result = bot.execute_trading_cycle(prices, order_book, model_prob)
    
    print(f"\n📊 REGIME DETECTION:")
    print(f"   Market Regime: {result['regime']}")
    print(f"   Dominant Side: {result['dominant_side']}")
    
    print(f"\n📈 MARKET DATA:")
    print(f"   Market Price: ${result['market_price']:.4f}")
    print(f"   Model Probability: {result['model_probability']:.2%}")
    print(f"   Edge: {result.get('edge', abs(result['model_probability'] - result['market_price'])):.2%}")
    
    if result['action'] == 'execute':
        print(f"\n💰 POSITION SIZING (Modified Kelly):")
        sizes = result['position_sizes']
        print(f"   UP Position: ${sizes['up']:.2f}")
        print(f"   DOWN Position: ${sizes['down']:.2f}")
        print(f"   Total Exposure: ${sizes['total']:.2f}")
        print(f"   Kelly Fraction: {sizes['kelly_fraction']:.2%}")
        
        print(f"\n📋 EXECUTION PLAN:")
        print(f"   Total Orders: {result['total_orders']}")
        print(f"   Duration: {result['estimated_duration_sec']} seconds")
        
        print(f"\n🔵 UP ORDERS (Scaling-In):")
        for i, order in enumerate(result['up_orders'][:3], 1):  # Tampilkan 3 pertama
            print(f"   {i}. Size: ${order['size']:.2f} | Limit: ${order['limit_price']:.4f} | Delay: {order['execution_delay_sec']:.1f}s")
        if len(result['up_orders']) > 3:
            print(f"   ... dan {len(result['up_orders']) - 3} orders lainnya")
        
        print(f"\n🔴 DOWN ORDERS (Insurance):")
        for i, order in enumerate(result['down_orders'][:3], 1):  # Tampilkan 3 pertama
            print(f"   {i}. Size: ${order['size']:.2f} | Limit: ${order['limit_price']:.4f} | Delay: {order['execution_delay_sec']:.1f}s")
        if len(result['down_orders']) > 3:
            print(f"   ... dan {len(result['down_orders']) - 3} orders lainnya")
        
        print(f"\n✅ STRATEGY NOTES:")
        print(f"   • Semua orders adalah LIMIT ORDERS (Maker) untuk menghindari fees")
        print(f"   • Scaling-in selama {config.scale_duration_sec}s untuk mengurangi slippage")
        print(f"   • Posisi asuransi ({sizes['down']:.2f}) berfungsi sebagai hedge")
        print(f"   • Hold to maturity (5 menit) untuk binary settlement")
    else:
        print(f"\n⚠️  NO TRADE: {result['reason']}")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    example_usage()
