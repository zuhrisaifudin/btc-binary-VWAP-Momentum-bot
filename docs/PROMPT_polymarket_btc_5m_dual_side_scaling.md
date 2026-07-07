# Strategi Dual-Side Scaling & Regime Adaptation
## Polymarket BTC 5M Up/Down Trading Bot

---

## Ringkasan Eksekutif

Strategi trading otomatis untuk pasar biner Polymarket "BTC 5M Up/Down" yang mengombinasikan:
- **Regime Detection** menggunakan Hurst Exponent + Order Flow Imbalance (OFI)
- **Kelly Criterion termodifikasi** (Half-Kelly) untuk sizing optimal
- **Dual-Side Allocation** (75% dominant + 25% insurance/trap)
- **Smart Scaling-In** maker limit order dengan fallback taker
- **Risk Management** berlapis (circuit breaker, daily stop-loss, spread gate)

---

## 1. Regime Detection

### 1.1 Hurst Exponent (H)
Mengukur persistensi/memori jangka panjang dari time series harga BTC.

**Kalkulasi:**
```python
def calculate_hurst(prices: List[float]) -> float:
    # 1. Hitung log returns
    returns = np.diff(np.log(prices))
    
    # 2. Rescaled Range (R/S) Analysis pada multiple lags
    for lag in [N/2, N/4, N/8, ...]:
        rs = R/S untuk setiap sub-interval
        
    # 3. Linear regression: log(R/S) = H * log(lag) + c
    H = slope dari regression
    return np.clip(H, 0.0, 1.0)
```

**Interpretasi:**
| H Value | Regime | Karakteristik |
|---------|--------|---------------|
| H > 0.55 | TRENDING | Persistent, trend-following efektif |
| H < 0.45 | MEAN_REVERTING | Anti-persistent, reversal efektif |
| 0.45 ≤ H ≤ 0.55 | NEUTRAL | Random walk, hindari trading agresif |

**Fix Sample Std:** Gunakan `ddof=1` untuk unbiased estimator:
```python
s = np.std(subset, ddof=1)  # BUKAN np.std(subset)
```

### 1.2 Order Flow Imbalance (OFI)
Mengukur tekanan beli/jual dari order book.

**Kalkulasi Multi-Level (Top 3 levels):**
```python
def update_multi_level(bids, asks) -> float:
    sorted_bids = sorted(bids, key=lambda x: x["price"], reverse=True)[:3]
    sorted_asks = sorted(asks, key=lambda x: x["price"])[:3]
    
    total_bid_size = sum(float(x["size"]) for x in sorted_bids)
    total_ask_size = sum(float(x["size"]) for x in sorted_asks)
    
    ofi = total_bid_size - total_ask_size
    return ofi
```

**Interpretasi:**
- OFI > 0: Tekanan beli dominan → bias UP
- OFI < 0: Tekanan jual dominan → bias DOWN
- OFI MA (moving average): Smooth noise high-frequency

### 1.3 Deteksi Arah Dominan
```python
def detect_with_direction(hurst, ofi_ma, recent_move_pct) -> Tuple[str, Optional[str]]:
    regime = detect(hurst, ofi_ma)  # TRENDING/MEAN_REVERTING/NEUTRAL
    
    if regime == "TRENDING":
        dominant_side = "UP" if ofi_ma > 0 else "DOWN"
    elif regime == "MEAN_REVERTING":
        # Lawan move terakhir
        dominant_side = "DOWN" if recent_move_pct > 0 else "UP"
    else:  # NEUTRAL
        dominant_side = None
    
    return regime, dominant_side
```

### 1.4 Orchestrator Function
```python
def detect_market_regime(
    prices: List[float],
    bids: List[Dict],
    asks: List[Dict],
    recent_move_pct: float
) -> Dict:
    """
    Returns: {
        'regime': str,           # TRENDING/MEAN_REVERTING/NEUTRAL
        'dominant_side': str,    # UP/DOWN/None
        'hurst': float,
        'ofi': float,
        'ofi_ma': float
    }
    """
    hurst = HurstExponentCalculator.calculate(prices)
    ofi = ofi_calculator.update_multi_level(bids, asks)
    ofi_ma = moving_average(ofi_history, window=5)
    
    regime, dominant_side = detect_with_direction(hurst, ofi_ma, recent_move_pct)
    
    return {
        'regime': regime,
        'dominant_side': dominant_side,
        'hurst': hurst,
        'ofi': ofi,
        'ofi_ma': ofi_ma
    }
```

---

## 2. Kelly Criterion Termodifikasi

### 2.1 Formula Dasar
Untuk binary options dengan payoff $1:
```
f* = (p - P) / (P * (1 - P))
```
Dimana:
- `p` = probabilitas menang (win rate estimate)
- `P` = harga token saat ini (implies probability)
- `f*` = fraction of bankroll to allocate

### 2.2 Half-Kelly (Risk Reduction)
```python
def calculate_kelly(win_prob: float, price: float, half_kelly: bool = True) -> float:
    if price <= 0.01 or price >= 0.99:
        return 0.0
    
    p = np.clip(win_prob, 0.01, 0.99)
    edge = p - price
    
    if edge <= 0:  # No positive edge
        return 0.0
    
    f_star = edge / (price * (1.0 - price))
    
    # Minimum fraction threshold
    if f_star < 0.0025:
        return 0.0
    
    # Apply Half-Kelly
    if half_kelly:
        f_star *= 0.5
    
    # Cap maximum
    return min(f_star, 0.20)
```

### 2.3 Conservative Variant
Requisites tambahan:
- Minimum win rate: 55%
- Minimum edge: 2%
- Price range: 0.30 - 0.70
- Max fraction: 15%

---

## 3. Dual-Side Allocation Strategy

### 3.1 Split Configuration
```yaml
dominant_allocation_pct: 0.75   # 75% ke arah utama (regime-confirmed)
insurance_allocation_pct: 0.25  # 25% ke arah berlawanan (hedge/trap)
```

**Validasi:** `abs(dominant + insurance - 1.0) < 0.001`

### 3.2 Token Selection Logic
Berdasarkan `detect_market_regime()`:

```python
regime_info = detect_market_regime(prices, bids, asks, recent_move_pct)

if regime_info['dominant_side'] == "UP":
    main_token = UP_token
    insurance_token = DOWN_token
elif regime_info['dominant_side'] == "DOWN":
    main_token = DOWN_token
    insurance_token = UP_token
else:  # NEUTRAL atau tidak jelas
    # Default: ikut OFI sign atau skip trade
    if regime_info['ofi_ma'] > 0:
        main_token = UP_token
    else:
        main_token = DOWN_token
```

### 3.3 Execution Flow
1. Hitung total budget dari Kelly: `budget = kelly_fraction * bankroll`
2. Split: `main_budget = budget * 0.75`, `insurance_budget = budget * 0.25`
3. Execute main position (scaling-in)
4. Execute insurance position (instant atau scaling tergantung config)

---

## 4. Smart Scaling-In Engine

### 4.1 Maker-First Pricing
**BUY Order:**
- Limit price = `best_bid + offset`
- Offset mulai kecil (0.01), naik bertahap per slice
- Tidak melebihi `best_ask` (no chasing)

**SELL Order:**
- Limit price = `best_ask - offset`
- Offset mulai kecil, naik bertahap
- Tidak dibawah `best_bid`

### 4.2 Time-Weighted Slicing
```python
async def scale_in(
    token_id: str,
    total_budget: float,
    parts: int = 10,
    total_duration_sec: float = 12.0,  # 10 slices × 1.2s
    side: str = "BUY"
) -> Tuple[bool, float, int]:
    slice_budget = total_budget / parts
    interval = total_duration_sec / parts
    
    contracts_filled = 0
    total_cost = 0.0
    
    for i in range(parts):
        # Get current book state
        best_bid, best_ask = await get_book(token_id)
        
        # Maker pricing
        if side == "BUY":
            offset = 0.01 + (i * 0.005)  # Increase offset gradually
            limit_price = min(best_bid + offset, best_ask)
        else:
            offset = 0.01 + (i * 0.005)
            limit_price = max(best_ask - offset, best_bid)
        
        # Spread check
        spread = best_ask - best_bid
        if spread > max_spread_usd:
            logger.warning(f"Spread too wide: {spread}")
            continue
        
        # Place GTC limit order
        contracts = int(slice_budget / limit_price)
        order_id = await place_limit_order(token_id, contracts, limit_price, side)
        
        # Wait for fill (partial ok)
        fills = await get_order_fills(order_id)
        filled_contracts = sum(f.size for f in fills)
        
        if filled_contracts > 0:
            contracts_filled += filled_contracts
            total_cost += filled_contracts * limit_price
        
        # Cancel remaining
        await cancel_order(order_id)
        
        # Fallback to taker at last slices (slice 8+)
        if i >= 7 and contracts_filled < target_contracts:
            remaining = target_contracts - contracts_filled
            if side == "BUY":
                await market_buy(token_id, remaining)
            else:
                await market_sell(token_id, remaining)
        
        await asyncio.sleep(interval)
    
    avg_price = total_cost / contracts_filled if contracts_filled > 0 else 0.0
    return (contracts_filled > 0), avg_price, contracts_filled
```

### 4.3 Simulation Mode Realistis
Jangan asumsikan `success=True` = full fill! Model probabilistik:
```python
if simulation_mode:
    # Probabilitas fill berdasarkan jarak ke best_bid
    if side == "BUY":
        distance = best_ask - limit_price
        fill_prob = max(0.3, 1.0 - (distance * 10))
    
    if random.random() < fill_prob:
        # Full或部分 fill
        filled = contracts if random.random() > 0.3 else contracts // 2
    else:
        filled = 0
```

---

## 5. Risk Management

### 5.1 Circuit Breaker
Trigger setelah N consecutive losses:
```yaml
max_consecutive_losses: 3
circuit_breaker_duration_min: 15
```

Implementasi:
```python
if consecutive_losses >= max_consecutive_losses:
    circuit_breaker_until = time.time() + (duration_min * 60)
    block_all_entries()
```

### 5.2 Daily Stop-Loss
```yaml
max_daily_trades: 20
daily_stop_loss_usd: -5.0
```

Reset setiap hari baru (midnight UTC).

### 5.3 Spread Gate
Skip entry jika spread terlalu lebar:
```python
spread_usd = best_ask - best_bid
if spread_usd > max_spread_usd:  # e.g., 0.05
    logger.warning("Spread too wide, skipping entry")
    return
```

### 5.4 No-Entry Cutoff
Jangan entry jika waktu tersisa < threshold:
```yaml
no_entry_before_end_sec: 60  # Don't enter in last 60 seconds
```

---

## 6. Position Resolution & P&L Calculation

### 6.1 Outcome Determination
Prioritas:
1. **Gamma API** (`market.closed` + `outcomePrices`) — official resolution
2. **Chainlink Oracle** (BTC anchor vs current price) — fallback
3. **Last Price** (≥0.70 threshold) — legacy only, mark as inaccurate

### 6.2 Deferred Resolution Pattern
Saat market end tapi outcome belum tersedia:
```python
def add_pending_resolution(self, condition_id: str, end_time: float):
    """Snapshot posisi dan bebaskan slot untuk market berikutnya."""
    snapshot = {
        "position": self.position.__dict__,
        "condition_id": condition_id,
        "end_time": end_time
    }
    self.pending_resolutions.append(snapshot)
    self.position = None  # Free slot immediately
```

Resolve nanti via poller:
```python
async def resolve_pending_positions():
    for index, item in enumerate(pending_resolutions):
        # Poll Gamma API
        market_data = await GET(f"/markets/{slug}")
        
        if market_data['closed']:
            outcome_prices = market_data['outcomePrices']
            won = determine_winner(outcome_prices, item['token_name'])
            
            record, pnl = build_trade_record(item['position'], won, ...)
            trades.append(record)
            pending_resolutions.pop(index)
```

### 6.3 P&L dengan Hedge
```python
entry_cost = contracts * entry_price
hedge_cost = hedge_contracts * hedge_price

if won:
    pnl = (contracts - entry_cost) - hedge_cost
else:
    hedge_payout = hedge_contracts * 1.00  # Hedge wins $1 each
    pnl = (-entry_cost - hedge_cost) + hedge_payout
```

---

## 7. Logging & Monitoring

### 7.1 Simulation History
Format CSV:
```csv
event,time_utc,unix_ts,market_slug,side,contracts,entry_price,exit_price,
      entry_cost_usd,trade_pnl_usd,cumulative_pnl_usd,won,trade_number,
      total_closed_trades,win_rate_pct,max_dd_abs,max_dd_pct,hedged
```

**Critical:** Pastikan `trade_number` monoton naik (gunakan `markets_seen`).

### 7.2 JSON Summary
```json
{
  "trades": [...],
  "markets_seen": 93,
  "summary": {
    "total_pnl_usd": 12.34,
    "trade_count": 45,
    "wins": 28,
    "losses": 17,
    "win_rate_pct": 62.22,
    "avg_trade_pnl_usd": 0.274,
    "best_trade_pnl_usd": 3.50,
    "worst_trade_pnl_usd": -2.10
  }
}
```

---

## 8. Konfigurasi Lengkap

```yaml
simulation:
  enabled: true
  initial_balance: 100.0

entry:
  bet_amount_usd: 2.00
  no_entry_before_end_sec: 60

strategy:
  dominant_allocation_pct: 0.75
  insurance_allocation_pct: 0.25
  use_kelly: true
  half_kelly: true
  max_trap_price: 0.30

regime_strategy:
  hurst_window: 20
  ofi_ma_window: 5
  max_consecutive_losses: 3
  circuit_breaker_duration_min: 15

risk:
  max_daily_trades: 20
  daily_stop_loss_usd: -5.0
  max_spread_usd: 0.05

hedge:
  enabled: true
  hedge_ratio: 0.30
  hedge_only_if_profit: true
  min_floating_profit_pct: 50.0
```

---

## 9. Checklist Implementasi

- [ ] Hurst dengan `ddof=1` untuk sample std
- [ ] OFI multi-level (top 3 levels)
- [ ] `detect_with_direction()` return `(regime, dominant_side)`
- [ ] Kelly Half-Kelly dengan minimum edge check
- [ ] Dual-side split 75/25 dengan validasi sum=1.0
- [ ] Scaling-in maker pricing (`best_bid + offset`)
- [ ] Fallback taker di slice ke-8+
- [ ] Akuntansi fill akurat (bukan assume success=full)
- [ ] Spread check per-slice
- [ ] Deferred resolution pattern (`add_pending_resolution` + `resolve_pending`)
- [ ] `trade_number` monoton (pakai `markets_seen`)
- [ ] Circuit breaker + daily stop-loss
- [ ] No-entry cutoff sebelum market end
- [ ] Simulation history OPEN + CLOSE pair lengkap

---

## 10. Referensi

- **Hurst Exponent:** https://en.wikipedia.org/wiki/Hurst_exponent
- **Kelly Criterion:** https://en.wikipedia.org/wiki/Kelly_criterion
- **Order Flow Imbalance:** Cont, R., et al. (2014). "Price impact from order flow imbalance."
- **Polymarket API:** https://polymarket.github.io/polymarket-docs/
- **Gamma API:** https://gamma-api.polymarket.com/
