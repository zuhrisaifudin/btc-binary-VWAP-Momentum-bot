# Configuration Guide — Bot V3 (FastAPI Control Plane + Worker Event-Driven)

**Dokumen ini adalah acuan konfigurasi untuk Arsitektur Bot V3.** 
Jika Anda masih menggunakan V2, lihat dokumentasi legacy di `docs/legacy/`.

V3 memperkenalkan arsitektur **event-driven** dengan **FastAPI sebagai control plane**, 
**WebSocket untuk data real-time**, dan **guardrail rumus PnL** yang ketat sebelum setiap order.

---

## Ringkasan Perubahan V2 → V3

| Komponen | V2 (Legacy) | V3 (Target) |
|----------|-------------|-------------|
| **Data fill** | REST polling (lag 100ms–1s) | **WebSocket** (~50–150ms) |
| **Order book** | REST read | **WS book in-memory** |
| **Cek pra-order** | risk/inventory sederhana | **Guardrail rumus** `worst_case` + `Pu+Pd<1` |
| **Kontrol** | CLI / dashboard Rich | **FastAPI API** + WebSocket UI |
| **Eksekusi** | Loop monolitik | **MarketWorker per market** (single writer) |
| **Mode guardrail** | Tidak ada | `risk_free_only` | `spread_positive` | `off` |

---

## 1. Guardrail Config — Inti Keamanan V3

Ini adalah konfigurasi **paling penting** di V3. Guardrail menolak order yang berpotensi rugi besar.

```json
{
  "market_maker": {
    "guardrail": {
      "mode": "risk_free_only",
      "max_imbalance_shares": 14,
      "pair_margin": 0.02
    }
  }
}
```

### `mode` — Mode disiplin guardrail

| Mode | Deskripsi | Kapan dipakai |
|------|-----------|---------------|
| `"risk_free_only"` | **Place order HANYA jika `worst_case >= 0`** (posisi bebas rugi apa pun hasil market) | **Live trading wajib** |
| `"spread_positive"` | Place order jika `Pu + Pd < 1` (pasangan untung), tapi masih bisa rugi jika imbalance besar | Paper testing / replay |
| `"off"` | Tidak ada guardrail (meniru Bonereaper apa adanya) | **ANALISIS SAJA — JANGAN LIVE** |

**Rumus yang dipakai:**
- `worst_case = min(Su, Sd) - modal` — harus ≥ 0 untuk mode `risk_free_only`
- `Pu + Pd < 1` — syarat harga pasangan untung (spread positif)
- `imbalance = |Su - Sd|` — dibatasi `max_imbalance_shares`

### `max_imbalance_shares` — Batas exposure arah

Membatasi selisih share Up dan Down yang tidak berpasangan. Contoh:
- `Su = 100`, `Sd = 86` → `imbalance = 14` (masih OK)
- `Su = 100`, `Sd = 80` → `imbalance = 20` (**DITOLAK** jika max = 14)

Nilai default **14** berdasarkan analisis empiris Bonereaper (bucket 5-menit BTC).

### `pair_margin` — Margin aman untuk `Pu + Pd`

Order ditolak jika `Pu + Pd >= 1 - pair_margin`. Default **0.02** berarti:
- Pasangan harus dibeli dengan diskon minimal **2¢** di bawah $1.
- Contoh: `Pu = 0.40`, `Pd` harus ≤ `0.58` (bukan 0.60).

---

## 2. Capital Config — Batas Modal Sesi

```json
{
  "market_maker": {
    "capital": {
      "session_capital_usd": 20,
      "reserve_usd": 4,
      "max_order_usd": 2.50,
      "min_shares": 5
    }
  }
}
```

### `session_capital_usd` — Budget simulasi per sesi

**BUKAN** saldo venue otomatis. Ini batas modal yang boleh dipakai bot dalam satu sesi trading.
- Default: **$20** (untuk testing/paper)
- Live: sesuaikan dengan bankroll Anda (mis. $100–$500)

**Rumus budget tersedia:**
```
budget_sim = session_capital_usd - reserve_usd - modal_terkunci
modal_terkunci = Su×Pu + Sd×Pd
```

### `reserve_usd` — Dana yang tidak boleh dipakai

Selalu sisakan dana untuk keadaan darurat atau fee tak terduga.
- Default: **$4** (20% dari $20)
- Live: 10–20% dari `session_capital_usd`

### `max_order_usd` — Batas nominal satu leg BUY

Membatasi ukuran order tunggal untuk menghindari over-commitment.
- Default: **$2.50** (dari analisis Bonereaper: rata-rata fill kecil)
- Formula: `size = min(max_order_usd / harga, budget_tersedia)`

### `min_shares` — Minimum share per order

Contoh parameter; validasi minimum venue tetap wajib.
- Default: **5** (sesuai contoh simulasi)
- Venue mungkin punya aturan berbeda — selalu cek `GET /clob-markets/{condition_id}`

---

## 3. Runtime Config — Performa & Reliabilitas

```json
{
  "market_maker": {
    "runtime": {
      "book_debounce_ms": 25,
      "fill_queue_max": 1000,
      "reconnect_max_delay_s": 10,
      "shutdown_timeout_s": 15
    }
  }
}
```

### `book_debounce_ms` — Debounce requote

Membatasi frekuensi cancel-replace saat book berubah cepat.
- Default: **25 ms** (cukup cepat untuk 5-menit BTC)
- Terlalu rendah → banyak order cancel (fee risk)
- Terlalu tinggi → quote basi

### `fill_queue_max` — Batas antrean fill event

Fill **tidak boleh hilang** (fail-closed). Queue penuh = pause + cancel all.
- Default: **1000** event
- Monitor metric `fill_queue_depth`

### `reconnect_max_delay_s` — Maksimum delay reconnect WS

Exponential backoff dengan jitter saat WebSocket putus.
- Default: **10 detik**
- Pastikan cukup cepat untuk catch-up snapshot

### `shutdown_timeout_s` — Timeout shutdown aman

Saat stop: pause → cancel semua order → await task → tulis snapshot.
- Default: **15 detik**
- Jika gagal cancel → exit dengan alarm

---

## 4. Schedule Config — Profil Waktu Eksekusi

Berdasarkan analisis **80.188 fill nyata**: agresivitas berubah menurut detik ke expiry.

```json
{
  "market_maker": {
    "schedule": {
      "taker_until_s": 295,
      "maker_only_below_s": 60,
      "taper_size_below_s": 15,
      "taker_open_max": 0.56
    }
  }
}
```

### `taker_until_s` — Seed posisi awal (TAKER agresif)

- **Detik 295–300 (buka)**: **82% TAKER** — rebut posisi cepat saat book tipis
- Default: **295** (hanya 5 detik pertama)
- Setelah itu: transisi ke MAKER-dominan

### `maker_only_below_s` — Stop menyeberang spread

- **Detik 0–60**: **MAKER-only** (haram taker, bid pasif saja)
- Default: **60**
- Mendekati expiry: likuiditas keluar, jadi penyedia likuiditas

### `taper_size_below_s` — Kecilkan size di detik akhir

- **Detik 0–15**: size mengecil (cuma tangkap cash-out)
- Default: **15**

### `taker_open_max` — Peluang taker maksimum saat buka

- Default: **0.56** (56% peluang taker di 270–300s)
- Kurva menurun monoton: `p_agresif(t) ≈ clamp((t - 60) / 240, 0, 0.56)`

**Visualisasi profil waktu:**

```
t=300s BUKA ──────────────────────────────────► t=0s SETTLE
│                                                    │
│◄─ SEED ─►│◄────── GRID MAKER ──────►│◄─ MAKER-ONLY ─►│
  82% taker   56%→23% agresif           14%→0% agresif
```

---

## 5. API Config — FastAPI Control Plane

```json
{
  "market_maker": {
    "api": {
      "enabled": true,
      "host": "127.0.0.1",
      "port": 8000
    }
  }
}
```

### `enabled` — Aktifkan FastAPI server

- Default: **true** (V3 wajib pakai API untuk kontrol)
- Jika false: hanya worker jalan, tidak ada kontrol eksternal

### `host` — Bind address

- Default: **127.0.0.1** (localhost only)
- Production: bind ke jaringan privat, **JANGAN publik**
- CORS publik **dimatikan** default

### `port` — Port HTTP/WebSocket

- Default: **8000**
- Endpoint: `/health/live`, `/health/ready`, `/v1/*`, `/metrics`, `/v1/ws/dashboard`

**Environment variable wajib (JANGAN di config.json):**
```bash
BOT_API_TOKEN=your_secret_token_here
```

---

## 6. Price Dynamics — Harga Masuk Dinamis

Harga bid **tidak statis** — dihitung dari 3 batas:

### 1. Batas dari RUMUS (jaga `Pu+Pd < 1`)
```python
p_bid_UP_max   = 1 - Pd - margin      # supaya Pu' + Pd tetap < 1
p_bid_DOWN_max = 1 - Pu - margin
```

**Bahaya jika dilanggar:** 
- Pegang Up avg 0.05, beli Down @ 0.98 → `Pu+Pd = 1.03 > 1` → **pasangan rugi**

### 2. Batas dari SALDO (bankroll)
```python
size_bid = f(saldo_tersedia, max_exposure, harga)
```
- Saldo menipis → size mengecil & ladder lebih pendek

### 3. Batas dari IMBALANCE + WAKTU
```python
if |Su-Sd| ≈ max_imbalance di sisi X:
    hanya bid sisi X di harga jauh lebih murah
if mendekati expiry:
    ikuti book ke ekstrem, TAPI tetap ≤ cap rumus
```

**Harga final = minimum dari semua batas:**
```python
def harga_bid(sisi, book, inv, saldo, cfg):
    p_target = book.mid_bid(sisi)                     # dari quotes.py
    p_cap    = 1 - inv.p_lawan(sisi) - cfg.margin     # batas rumus
    p        = min(p_target, p_cap)                   # jangan langgar rumus
    size     = size_dari_saldo(saldo, p, cfg)         # batas bankroll
    
    if size <= 0 or inv.imbalance(sisi) >= cfg.max_imbalance:
        return None                                   # skip
    
    return p, size
```

---

## 7. Struktur config.json Lengkap (V3 Target)

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
    "runtime": {
      "book_debounce_ms": 25,
      "fill_queue_max": 1000,
      "reconnect_max_delay_s": 10,
      "shutdown_timeout_s": 15
    },
    "schedule": {
      "taker_until_s": 295,
      "maker_only_below_s": 60,
      "taper_size_below_s": 15,
      "taker_open_max": 0.56
    },
    "api": {
      "enabled": true,
      "host": "127.0.0.1",
      "port": 8000
    }
  }
}
```

**Environment variables (wajib, jangan di commit):**
```bash
# .env
BOT_API_TOKEN=secret_operator_token
POLYMARKET_API_KEY=...
POLYMARKET_API_SECRET=...
PRIVATE_KEY=0x...
```

---

## 8. Presets — Konfigurasi Siap Pakai

### Conservative (Testing/Paper)
```json
{
  "market_maker": {
    "guardrail": { "mode": "risk_free_only" },
    "capital": {
      "session_capital_usd": 20,
      "reserve_usd": 4,
      "max_order_usd": 2.50
    },
    "schedule": {
      "taker_until_s": 295,
      "maker_only_below_s": 60
    }
  }
}
```

### Moderate (Live Kecil)
```json
{
  "market_maker": {
    "guardrail": { 
      "mode": "risk_free_only",
      "max_imbalance_shares": 20
    },
    "capital": {
      "session_capital_usd": 100,
      "reserve_usd": 20,
      "max_order_usd": 5.00
    }
  }
}
```

### Aggressive (Hanya Analisis — JANGAN LIVE)
```json
{
  "market_maker": {
    "guardrail": { "mode": "off" },
    "capital": {
      "session_capital_usd": 500,
      "max_order_usd": 25.00
    }
  }
}
```
⚠️ **Mode `off` meniru Bonereaper: 85.4% market BUKAN risk-free, 53.1% `Pu+Pd >= 1`. 
Hanya untuk replay/analisis!**

---

## 9. Validasi & Preflight

Sebelum live, V3 menjalankan **preflight check**:
1. ✅ Validasi config (mode, margin, imbalance)
2. ✅ Cek saldo venue ≥ `session_capital_usd`
3. ✅ Test koneksi WS market & user
4. ✅ Probe CLOB gateway (post-only test)
5. ✅ Verifikasi market catalog (Up/Down token mapping)

Jika gagal → `/health/ready` returns **503**, worker tetap **PAUSED**.

---

## 10. Reload Konfig Dinamis

Endpoint `POST /v1/config/reload` mengizinkan reload parameter **tanpa restart**:
- ✅ `guardrail.pair_margin`
- ✅ `capital.max_order_usd` (turunkan saja, naikkan butuh restart)
- ✅ `schedule.maker_only_below_s`
- ❌ **Tidak boleh**: mode guardrail, credential, market aktif, paper→live

Reload memicu **cancel/requote atomik** jika perubahan memengaruhi quote aktif.

---

## Referensi Lanjutan

- **Arsitektur lengkap**: [`docs/ARSITEKTUR_V3.md`](docs/ARSITEKTUR_V3.md)
- **Rumus PnL detail**: `src/mm/pnl_formula.py`
- **Guardrail logic**: `src/mm/guardrail.py`
- **API endpoints**: `docs/README.md` → section API Contracts
- **Simulasi akumulasi**: `scripts/simulate_paired_orders.py`

---

**Peringatan:** Dokumentasi lama (`CONFIG.md` V2) masih ada di `docs/legacy/CONFIG_V2.md` untuk referensi migrasi. 
Semua deployment baru **WAJIB** mengikuti panduan V3 ini.
