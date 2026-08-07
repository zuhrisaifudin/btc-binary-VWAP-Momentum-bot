# Guardrail Rumus — Bot V3 (FastAPI Control Plane + Worker Event-Driven)

**Dokumen ini menggantikan GUIDELINE_DUAL_SIDE_REGIME.md V2.** 
Jika Anda masih menggunakan strategi dual-side scaling dengan Hurst Exponent dan OFI, 
dokumen itu **SUDAH USANG** dan tidak lagi relevan untuk Arsitektur V3.

V3 tidak menggunakan deteksi rezim, Kelly Criterion, atau scaling-in engine. 
Sebagai gantinya, V3 memakai **guardrail rumus PnL murni** yang deterministik dan fail-closed.

---

## Ringkasan: V2 vs V3

| Komponen | V2 (Legacy — HAPUS) | V3 (Target — PAKAI) |
|----------|---------------------|---------------------|
| **Deteksi arah** | Hurst Exponent + OFI | **Tidak ada** — bot netral dua sisi |
| **Sizing** | Modified Kelly Criterion | **Batas saldo + rumus `Pu+Pd<1`** |
| **Alokasi** | 75/25 split (dominant/insurance) | **Simetris dua sisi** — bid UP & DOWN bersamaan |
| **Eksekusi** | Scaling-in 10 slices (120s) | **Event-driven** — requote tiap book berubah |
| **Pengaman** | Circuit breaker (3 loss) | **Guardrail rumus** (`worst_case`, `imbalance`) |
| **Entry timing** | Cutoff 60s sebelum expiry | **Profil waktu** — taker 5s pertama, maker-only <60s |
| **Data source** | REST polling | **WebSocket** (book + fill real-time) |
| **Kontrol** | Web dashboard Rich | **FastAPI API** + WebSocket UI |

**Kesimpulan:** V2 adalah strategi **directional** (menebak arah BTC). 
V3 adalah strategi **market-making non-directional** (mengumpulkan spread dari kedua sisi).

---

## 1. Filosofi Guardrail V3

V3 tidak mencoba memprediksi apakah BTC akan naik atau turun. 
Sebaliknya, V3 mencari **pasangan token UP+DOWN yang dibeli di bawah $1**, 
lalu mengunci profit dari selisih tersebut melalui mekanisme **merge/redeem**.

### Sumber Profit V3

```
Laba bruto = M × (1 - Pu - Pd)

di mana:
  M  = min(Su, Sd)          # share berpasangan
  Pu = harga rata-rata UP   # cost_u / Su
  Pd = harga rata-rata DOWN # cost_d / Sd
```

**Syarat profit:**
- `Pu + Pd < 1` → pasangan untung (spread positif)
- `M > 0` → sudah ada pasangan yang terbentuk

**Contoh:**
```
BUY UP   5 share @ $0.40  → biaya $2.00
BUY DOWN 5 share @ $0.50  → biaya $2.50

Su=5, Sd=5, Pu=0.40, Pd=0.50
modal = $4.50
laba_pasangan = 5 × (1 - 0.40 - 0.50) = +$0.50
```

Ini adalah **arbitrase harga**, bukan prediksi arah.

---

## 2. Guardrail Rumus — Tiga Lapis Pengaman

Setiap kandidat order **WAJIB** lulus tiga tes ini sebelum dieksekusi:

### Lapis 1: `worst_case >= 0` (Risk-Free Only)

```python
worst_case = min(Su, Sd) - modal
modal = Su×Pu + Sd×Pd
```

**Arti:** Posisi harus bebas rugi apa pun hasil market (UP menang atau DOWN menang).

**Mode guardrail:**
- `"risk_free_only"` → WAJIB `worst_case >= 0` (live trading)
- `"spread_positive"` → Cukup `Pu+Pd < 1` (paper testing, masih bisa rugi jika imbalance)
- `"off"` → Tidak ada guardrail (**JANGAN LIVE** — hanya analisis Bonereaper)

**Statistik Bonereaper (analisis empiris):**
- Hanya **14.6%** market yang risk-free (`worst_case >= 0`)
- **46.9%** market punya `Pu+Pd >= 1` (pasangan rugi)
- **85.4%** market BUKAN risk-free

→ Ini mengapa V3 wajib pakai mode `risk_free_only` untuk live.

### Lapis 2: `Pu + Pd < 1 - pair_margin` (Spread Positif)

Order ditolak jika harga rata-rata pasangan terlalu dekat dengan $1.

**Default margin:** `0.02` (2¢)
- Contoh: `Pu = 0.40` → `Pd` harus ≤ `0.58` (bukan 0.60)
- Tujuannya:留出 buffer untuk fee, slippage, dan pembulatan venue

**Bahaya jika dilanggar:**
```
Pegang Up avg 0.05, beli Down @ 0.98
→ Pu+Pd = 1.03 > 1
→ Pasangan rugi $0.03 per share
```

### Lapis 3: `imbalance <= max_imbalance_shares` (Batasi Exposure Arah)

```python
imbalance = |Su - Sd|
```

Membatasi share yang tidak berpasangan (net exposure).

**Default:** `14` shares (berdasarkan analisis bucket 5-menit BTC)

**Contoh:**
```
Su = 100, Sd = 86  → imbalance = 14  ✓ OK
Su = 100, Sd = 80  → imbalance = 20  ✗ DITOLAK
```

**Kenapa penting?**
Dari contoh akumulasi Bonereaper (BTC 11:10–11:15):
```
Su = 262 @ 0.139, Sd = 44 @ 0.725
Pu+Pd = 0.864 < 1  ✓ pasangan untung
matched = 44, imbalance = 218  ✗ exposure besar

Down menang → PnL = -$24.33 (rugi meski Pu+Pd < 1)
```

→ Spread pasangan (+$5.98) kalah oleh kerugian exposure Up (+$218 @ 0.139).

---

## 3. Alur Keputusan Order (Pseudocode)

```python
def izinkan_bid(sisi, p, q, inv, cfg):
    """
    Guardrail check sebelum place order.
    
    Args:
        sisi: "UP" atau "DOWN"
        p: harga bid kandidat
        q: size (share)
        inv: inventori sekarang (Su, Sd, Pu, Pd, cost_u, cost_d)
        cfg: config guardrail (mode, max_imbalance, pair_margin)
    
    Returns:
        (bool, str): (allowed, reason)
    """
    # 1. Proyeksi posisi PASCA-fill
    Su, Sd = inv.su, inv.sd
    Pu, Pd = inv.pu, inv.pd
    cost_u, cost_d = inv.cost_u, inv.cost_d
    
    if sisi == "UP":
        Su = inv.su + q
        Pu = (cost_u + q * p) / Su
    else:
        Sd = inv.sd + q
        Pd = (cost_d + q * p) / Sd
    
    # 2. Hitung metrik kunci
    wc, risk_free = worst_case(Su, Pu, Sd, Pd)
    sum_price = Pu + Pd
    imbalance = abs(Su - Sd)
    
    # 3. Tes Lapis 3: Imbalance cap
    if imbalance > cfg.max_imbalance_shares:
        return False, f"imbalance {imbalance} > max {cfg.max_imbalance_shares}"
    
    # 4. Tes Lapis 1: Risk-free (jika mode aktif)
    if cfg.mode == "risk_free_only" and not risk_free:
        return False, f"worst_case {wc:.2f} < 0 (bukan risk-free)"
    
    # 5. Tes Lapis 2: Spread positif
    if cfg.mode == "spread_positive" and sum_price >= 1 - cfg.pair_margin:
        return False, f"Pu+Pd {sum_price:.3f} >= {1 - cfg.pair_margin:.2f} (pasangan rugi)"
    
    # 6. Lolos semua tes
    return True, "ok"
```

**Catatan:** Fungsi `worst_case()` ada di `src/mm/pnl_formula.py`:
```python
def worst_case(su, pu, sd, pd):
    modal = su * pu + sd * pd
    wc = min(su, sd) - modal
    risk_free = wc >= 0
    return wc, risk_free
```

---

## 4. Harga Masuk Dinamis

Harga bid **tidak statis** — dihitung ulang setiap event berdasarkan 3 batas:

### Batas 1: Rumus (Cap dari sisi lawan)

```python
p_bid_UP_max   = 1 - Pd - margin
p_bid_DOWN_max = 1 - Pu - margin
```

**Contoh bahaya:**
- Pegang Up avg 0.05 → `p_bid_DOWN_max = 1 - 0.05 - 0.02 = 0.93`
- Jika book menawarkan Down @ 0.98 → **TOLAK** (akan bikin `Pu+Pd = 1.03`)

### Batas 2: Saldo (Budget tersedia)

```python
budget_sim = session_capital_usd - reserve_usd - modal_terkunci
modal_terkunci = Su×Pu + Sd×Pd

size_max = budget_sim / p_bid
```

- Saldo menipis → size mengecil otomatis
- Jangan over-leverage: `max_order_usd` tetap berlaku

### Batas 3: Waktu ke Expiry (Profil agresivitas)

```python
if secs_to_expiry > 295:       # 5 detik pertama
    mode = TAKER_AGGRESSIVE    # 82% taker, seed posisi cepat
elif secs_to_expiry > 60:      # Tengah window
    mode = MAKER_DOMINANT      # 56%→23% taker, quote pasif
else:                          # <60 detik
    mode = MAKER_ONLY          # 0% taker, haram menyeberang spread
```

**Harga final:**
```python
def harga_bid(sisi, book, inv, saldo, cfg, secs_to_expiry):
    # Batas dari book (ikuti mid bid)
    p_target = book.mid_bid(sisi)
    
    # Batas dari rumus (jaga Pu+Pd < 1)
    p_cap = 1 - inv.p_lawan(sisi) - cfg.pair_margin
    
    # Ambil minimum (jangan langgar rumus)
    p = min(p_target, p_cap)
    
    # Hitung size dari saldo
    size = min(
        cfg.max_order_usd / p,
        saldo / p,
        secs_to_decay_size(secs_to_expiry)  # kecilkan size dekat expiry
    )
    
    # Cek imbalance
    if inv.imbalance(sisi) >= cfg.max_imbalance_shares:
        return None  # skip
    
    return p, size
```

---

## 5. Profil Waktu Eksekusi (Data Empiris 80.188 Fill)

V3 meniru perilaku Bonereaper yang **terukur**, bukan spekulatif:

| Detik ke Expiry | Fill Count | Maker % | Taker % | Fase |
|-----------------|------------|---------|---------|------|
| **295–300** (buka) | 1.545 | 18% | **82%** | **TAKER agresif** — seed posisi |
| 240–295 | 14.928 | 54% | 46% | Transisi |
| 180–240 | 16.298 | 61% | 39% | Maker-dominan |
| 120–180 | 15.313 | 61% | 39% | Maker-dominan |
| 60–120 | 16.003 | 66% | 34% | Maker naik |
| 30–60 | 8.872 | 77% | 23% | Maker |
| 15–30 | 4.582 | 80% | 20% | Maker |
| **0–15** (akhir) | 1.557 | **97%** | 3% | **MAKER murni** — likuiditas keluar |
| <0 (settle) | 1.090 | 100% | 0% | Pasif total |

**Implikasi konfigurasi:**
```json
{
  "schedule": {
    "taker_until_s": 295,          # Hanya 5 detik pertama
    "maker_only_below_s": 60,      # Stop taker di 60 detik terakhir
    "taper_size_below_s": 15,      # Kecilkan size di 15 detik akhir
    "taker_open_max": 0.56         # Peluang taker maks 56%
  }
}
```

**Kenapa pola ini?**
- **Buka (5 detik pertama):** Book tipis, spread lebar → taker untuk rebut posisi awal cepat
- **Tengah:** Book stabil → maker untuk hemat fee (rebate)
- **Akhir (<60s):** Likuiditas keluar, risiko settle tinggi → jadi penyedia likuiditas (maker-only)

---

## 6. Akumulasi Posisi (Running Average)

Bot tidak beli sekali — akumulasi terus sepanjang window 300 detik.

### Rumus Average Berjalan

```python
# Setiap fill UP: q share @ harga p
Su_baru = Su + q
cost_u_baru = cost_u + q * p
Pu_baru = cost_u_baru / Su_baru

# Setiap fill DOWN: q share @ harga p
Sd_baru = Sd + q
cost_d_baru = cost_d + q * p
Pd_baru = cost_d_baru / Sd_baru
```

**Contoh dari screenshot Bonereaper (BTC 11:10–11:15):**
```
Su = 840.29 @ Pu = 0.336
Sd = 994.91 @ Pd = 0.619

Pu + Pd = 0.955 < 1  ✓ pasangan untung
matched = 840, imbalance = 155 (net Down)
modal = $898.19
worst_case = 840 - 898.19 = -$57.90  ✗ BUKAN risk-free

Down menang → payout = 994.91 - 898.19 = +$96.72
Up menang → payout = 840 - 898.19 = -$57.90
```

**Pelajaran:**
- Akumulasi harga rapi (`Pu+Pd < 1`) ✅
- Tapi imbalance besar (155 shares) ❌
- Hasil: masih berisiko rugi -$58 meski pasangan untung

→ V3 lebih ketat: batasi `max_imbalance_shares = 14` agar akumulasi tidak keluar dari `worst_case >= 0`.

---

## 7. Konfigurasi Guardrail (Wajib)

```json
{
  "market_maker": {
    "guardrail": {
      "mode": "risk_free_only",
      "max_imbalance_shares": 14,
      "pair_margin": 0.02
    },
    "capital": {
      "session_capital_usd": 20,
      "reserve_usd": 4,
      "max_order_usd": 2.50,
      "min_shares": 5
    },
    "schedule": {
      "taker_until_s": 295,
      "maker_only_below_s": 60,
      "taper_size_below_s": 15,
      "taker_open_max": 0.56
    }
  }
}
```

**Parameter kritis:**
- `mode`: WAJIB `"risk_free_only"` untuk live
- `max_imbalance_shares`: 14 (default empiris), naikkan hanya setelah backtest ketat
- `pair_margin`: 0.02 (buffer 2¢ untuk fee/slippage)
- `session_capital_usd`: Bukan saldo venue — ini batas modal sesi (simulasi)

---

## 8. Simulasi Accumulasi (CLI)

V3 menyediakan simulator REPL untuk uji akumulasi tanpa I/O CLOB:

```bash
# Mode risk_free_only, modal $20, reserve $4, max order $2.50
python scripts/simulate_paired_orders.py \
  --mode risk_free_only \
  --capital-usd 20 \
  --reserve-usd 4 \
  --max-order-usd 2.50 \
  --min-shares 5
```

**Perintah simulator:**
```
sim> pairusd 0.40 2.00 0.50 2.50   # Beli pasangan UP/DOWN
sim> show                            # Lihat Su, Sd, Pu, Pd, worst_case
sim> buy up 5 0.38                   # Uji beli UP tambahan
sim> guardrail                       # Cek decision guardrail
sim> reset                           # Reset inventori
```

**Output contoh:**
```
Position:
  Su=5, Sd=5, Pu=0.40, Pd=0.50
  Modal=$4.50, worst_case=+$0.50 (risk-free ✓)
  matched=5, imbalance=0
  spread_pair=5×(1-0.40-0.50)=+$0.50

Budget:
  session_capital=$20, reserve=$4
  modal_terkunci=$4.50, budget_tersedia=$11.50
```

---

## 9. Peringatan Penting

### ⚠️ JANGAN Pakai Mode `off` untuk Live

```json
"guardrail": { "mode": "off" }  # ❌ BAHAYA!
```

Mode ini meniru Bonereaper apa adanya:
- 85.4% market BUKAN risk-free
- 53.1% market punya `Pu+Pd >= 1` (pasangan rugi)
- Imbalance tidak terkendali (bisa >200 shares)

**Hanya untuk:**
- Replay historis
- Analisis statistik
- Backtesting strategi

### ⚠️ Mode `spread_positive` Bukan Janji Profit

```json
"guardrail": { "mode": "spread_positive" }  # ⚠️ Masih bisa rugi
```

Mode ini cukup cek `Pu+Pd < 1`, tapi:
- Masih bisa rugi jika imbalance besar
- Contoh: `Pu+Pd=0.86 < 1` ✅, tapi `imbalance=218` ❌ → rugi -$24

**Gunakan hanya untuk:**
- Paper testing
- Validasi rumus
- Bukan live trading

### ✅ Mode `risk_free_only` Wajib untuk Live

```json
"guardrail": { "mode": "risk_free_only" }  # ✅ AMAN
```

Ini satu-satunya mode yang menjamin:
- `worst_case >= 0` (bebas rugi apa pun hasil market)
- `imbalance <= max` (exposure terkontrol)
- `Pu+Pd < 1 - margin` (spread positif dengan buffer)

---

## 10. Referensi Lanjutan

- **Arsitektur lengkap**: [`docs/ARSITEKTUR_V3.md`](docs/ARSITEKTUR_V3.md)
- **Rumus detail**: `src/mm/pnl_formula.py`
- **Guardrail logic**: `src/mm/guardrail.py`
- **Simulator**: `scripts/simulate_paired_orders.py`
- **Config guide**: [`CONFIG.md`](CONFIG.md)

---

**Dokumentasi lama (V2)** tentang Hurst Exponent, OFI, Kelly Criterion, dan dual-side scaling 
telah dipindahkan ke `docs/legacy/GUIDELINE_V2.md` untuk referensi sejarah migrasi.

**Semua deployment baru WAJIB mengikuti panduan guardrail V3 ini.**
