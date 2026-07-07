# Dual-Side Scaling Strategy - Panduan Penggunaan

## Ringkasan
Dokumentasi mengenai implementasi strategi dual-side scaling dengan regime detection untuk Polymarket BTC Binary Bot.

## Komponen Utama

### 1. MarketRegimeAnalyzer
Menganalisis regime pasar menggunakan Hurst Exponent dan Order Flow Imbalance.

```python
from src.market_regime_analyzer import MarketRegimeAnalyzer

# Inisialisasi
analyzer = MarketRegimeAnalyzer(
    price_window=20,
    ofi_window=5,
    min_price_threshold=0.30,
    max_price_threshold=0.70
)

# Update data
analyzer.update_price(0.55)
analyzer.update_order_book(bids, asks)

# Analisis regime
regime_info = analyzer.analyze_regime()
summary = analyzer.get_regime_summary()
```

**Output:**
- `regime`: "TRENDING", "MEAN_REVERTING", atau "NEUTRAL"
- `dominant_side`: "UP", "DOWN", atau None
- `confidence`: Skor kepercayaan 0-1

### 2. SmartScalingEngine
Executor untuk scaling-in dengan pricing maker yang cerdas.

```python
from src.smart_scaling_engine import SmartScalingEngine, ScalingConfig

# Konfigurasi
config = ScalingConfig(
    parts=10,                    # Jumlah slice
    total_duration_sec=120.0,    # Total durasi
    initial_offset_usd=0.01,    # Offset awal
    offset_increment_usd=0.005,  # Increment offset
    max_spread_usd=0.05,        # Max spread
    taker_fallback_start=8      # Mulai taker di slice 8
)

# Inisialisasi
engine = SmartScalingEngine(executor, config)

# Eksekusi scaling
result = await engine.scale_in(
    token_id="token123",
    total_budget=10.0,
    side="BUY"
)
```

### 3. KellyCriterionCalculator
Perhitungan Kelly Criterion dengan konservatif dan standard.

```python
from src.regime_strategy import KellyCriterionCalculator

# Standard Kelly
fraction = KellyCriterionCalculator.calculate(
    win_prob=0.60,
    price=0.50
)

# Conservative Kelly (rekomendasi)
fraction = KellyCriterionCalculator.calculate_conservative(
    win_prob=0.60,
    price=0.50
)
```

### 4. DualSideScalingManager
Manajer utama yang menggabungkan semua komponen.

```python
from src.dual_side_scaling_manager import DualSideScalingManager, DualSideConfig

# Konfigurasi
config = DualSideConfig(
    scaling_parts=10,
    scaling_duration_sec=120.0,
    use_conservative_kelly=True,
    dominant_allocation_pct=0.75,
    insurance_allocation_pct=0.25,
    max_daily_trades=20,
    daily_stop_loss_usd=-5.0
)

# Inisialisasi
manager = DualSideScalingManager(order_executor, config)

# Eksekusi trade
success, result = await manager.execute_dual_side_trade(
    up_token_id="up123",
    down_token_id="down123",
    win_prob=0.58
)
```

## Konfigurasi di config.json

### Tambahkan setting untuk dual-side scaling:

```json
{
  "regime_strategy": {
    "enabled": true,
    "total_budget_usd": 20.00,
    "hurst_threshold_trending": 0.55,
    "hurst_threshold_mean_revert": 0.45,
    "dominant_allocation_pct": 0.75,
    "insurance_allocation_pct": 0.25,
    "scaling_parts": 10,
    "scaling_duration_sec": 120.0,
    "max_consecutive_losses": 5,
    "circuit_breaker_duration_min": 60,
    "max_spread_usd": 0.05
  },
  "strategy": {
    "min_price": 0.30,
    "max_price": 0.70,
    "min_elapsed_sec": 60,
    "min_deviation_pct": 1.0,
    "no_entry_before_end_sec": 60
  }
}
```

## Integrasi dengan Main Bot

### 1. Update Imports di main.py

```python
from src.dual_side_scaling_manager import DualSideScalingManager, DualSideConfig
from src.market_regime_analyzer import MarketRegimeAnalyzer
from src.smart_scaling_engine import SmartScalingEngine, ScalingConfig
```

### 2. Tambahkan ke Bot Class

```python
class TradingBot:
    def __init__(self):
        # Existing initialization...
        
        # Initialize dual-side manager
        self.dual_side_manager = DualSideScalingManager(
            order_executor=self.executor,
            config=DualSideConfig()
        )
```

### 3. Update Signal Handling

```python
async def handle_signal(self, signal_type, token_name, token_data):
    if signal_type == "REGIME_SIGNAL":
        # Update regime analyzer
        self.dual_side_manager.update_price_data(token_data["price"])
        self.dual_side_manager.update_order_book_data(
            token_data["bids"], 
            token_data["asks"]
        )
        
        # Check if should trade
        if self.dual_side_manager.should_trade_regime(token_data["price"]):
            decision = self.dual_side_manager.calculate_trade_decision()
            
            if decision and decision.should_trade:
                # Execute dual-side trade
                success, result = await self.dual_side_manager.execute_dual_side_trade(
                    up_token_id=self.state.up_token.token_id,
                    down_token_id=self.state.down_token.token_id,
                    win_prob=decision.regime_info.win_prob
                )
```

## Parameter Penting

### Regime Detection
- `hurst_threshold_trending`: H > 0.55 = TRENDING
- `hurst_threshold_mean_revert`: H < 0.45 = MEAN_REVERTING
- `price_window`: Jumlah harga untuk kalkulasi Hurst
- `ofi_window`: Jumlah data OFI untuk smoothing

### Kelly Criterion
- `use_conservative_kelly`: Gunakan versi konservatif (rekomendasi)
- `min_win_rate_threshold`: 55% untuk konservatif
- `min_edge_threshold`: 2% untuk konservatif

### Scaling
- `scaling_parts`: Jumlah order slice (10-20)
- `scaling_duration_sec`: Total waktu scaling (60-300 detik)
- `initial_offset_usd`: Offset awal limit price (0.01-0.02)
- `offset_increment_usd`: Increment per slice (0.005-0.01)

### Risk Management
- `max_consecutive_losses`: Trigger circuit breaker
- `circuit_breaker_duration_min`: Durasi circuit breaker
- `max_daily_trades`: Batas trade per hari
- `daily_stop_loss_usd`: Stop loss harian

## Monitoring dan Logging

### Log yang Tersedia

1. **Regime Analysis** (`logs/regime.log`)
   - Deteksi regime
   - Confidence score
   - Perubahan regime

2. **Kelly Calculation** (`logs/kelly.log`)
   - Input/output Kelly
   - Allokasi budget
   - Keputusan trade

3. **Scaling Execution** (`logs/scaling.log`)
   - Detail setiap slice
   - Fill rate
   - Average price

4. **Dual-Side Summary** (`logs/dual_side.log`)
   - Trade decisions
   - Performance
   - Risk metrics

### Metrics Penting

```python
# Dapatkan summary
summary = self.dual_side_manager.get_summary()

print(f"Daily Trades: {summary['daily_trades']}")
print(f"Daily P&L: ${summary['daily_pnl']:.2f}")
print(f"Consecutive Losses: {summary['consecutive_losses']}")
print(f"Regime Count: {summary['regime_count']}")
```

## Best Practices

### 1. Testing
- Selalu test di simulation mode terlebih dahulu
- Gunakan data historik untuk backtest
- Monitor performance dengan berbagai parameter

### 2. Risk Management
- Gunakan conservative Kelly untuk mengurangi drawdown
- Set daily stop loss yang wajar
- Monitor consecutive losses

### 3. Performance Tuning
- Adjust regime thresholds berdasarkan data historik
- Optimalkan scaling parameters
- Update win rate estimation secara berkala

### 4. Monitoring
- Periksa logs secara regular
- Track win rate per regime
- Monitor fill rate dan slippage

## Troubleshooting

### Masalah Umum

1. **Regime selalu NEUTRAL**
   - Perlu lebih banyak data harga (price_window)
   - Cek perhitungan OFI
   - Kurangi threshold H untuk deteksi yang lebih sensitif

2. **Kelly selalu 0**
   - Win prob < price (tidak ada edge)
   - Price di luar range valid
   - Check data win rate CSV

3. **Scaling tidak successful**
   - Spread terlalu lebar
   - Volume rendah
   - Kurangi parts atau duration

4. **High consecutive losses**
   - Cek regime detection accuracy
   - Adjust Kelly fraction
   - Implementasi circuit breaker

### Debug Mode

Untuk debugging, aktifkan logging detail:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Ini akan menampilkan semua perhitungan dan keputusan.

## Next Steps

1. Update konfigurasi di config.json
2. Implementasikan integrasi ke main.py
3. Jalankan di simulation mode
4. Monitor dan tune parameters
5. Implementasikan di live trading dengan modal kecil

## Referensi

- [Hurst Exponent](https://en.wikipedia.org/wiki/Hurst_exponent)
- [Kelly Criterion](https://en.wikipedia.org/wiki/Kelly_criterion)
- [Order Flow Imbalance](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=495912)
- [Polymarket API](https://polymarket.github.io/polymarket-docs/)