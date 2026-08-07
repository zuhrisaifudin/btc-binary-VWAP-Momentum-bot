# Arsitektur Bot v3 — FastAPI Control Plane + Worker Event-Driven

**Status**: Dokumen ini adalah **rancangan target V3**, bukan klaim bahwa semua file sudah ada.

## Ringkasan Eksekutif

Arsitektur V3 adalah migrasi besar dari bot trading Polymarket dengan tiga prinsip utama:

1. **FastAPI Control Plane** - API untuk kontrol, monitoring, dan observabilitas (bukan jalur trading)
2. **Worker Event-Driven** - Satu worker per market dengan event loop WebSocket real-time
3. **Guardrail Rumus PnL** - Setiap order divalidasi dengan formula `worst_case >= 0` dan `Pu+Pd < 1`

### Perbedaan V1 vs V2 vs V3

| Aspek | V1 (Scalper) | V2 (Grid Maker) | **V3 (Event-Driven)** |
|-------|-------------|-----------------|----------------------|
| Gaya Trading | Taker penebak arah | Grid maker dua-sisi | Grid maker + guardrail rumus |
| Data Fill | — | REST polling (lag 100ms-1s) | **WebSocket (~50-150ms)** |
| Order Book | — | REST read | **WS in-memory** |
| Cek Pra-Order | — | Risk/inventory | **+ Guardrail rumus** |
| Status | ❌ Ditinggalkan | ⚠️ Live-ready | ✅ Target produksi |

---

## Flow Utama (Event Loop)

```
        ┌─────────────────────── Polymarket CLOB ───────────────────────┐
        │  WS market channel          WS user channel        REST order  │
        └────────┬────────────────────────┬──────────────────────┬──────┘
                 │ book delta              │ fill                 ▲ place/cancel
                 ▼                         ▼                      │
        ┌─────────────────┐      ┌──────────────────┐            │
        │ market_stream   │      │ user_stream (WS) │            │
        │ book in-memory  │      │ update inventori │            │
        └────────┬────────┘      └────────┬─────────┘            │
                 │ event "book berubah"    │ event "fill"        │
                 └───────────┬─────────────┘                     │
                             ▼                                   │
                  ┌─────────────────────┐                        │
                  │   QUOTE ENGINE      │                        │
                  │ 1. baca inventori   │                        │
                  │ 2. hitung quote     │                        │
                  │ 3. GUARDRAIL RUMUS  │────── lolos ──────────►│ executor
                  │ 4. place / skip     │────── ditolak ─► buang │
                  └─────────────────────┘                        │
                             ▲                                   │
                             └───────── fill balik ──────────────┘
```

### Langkah per Event

1. **Baca inventori**: `Su, Sd` (share Up/Down), `cost_u, cost_d` → `Pu = cost_u/Su`, `Pd = cost_d/Sd`
2. **Hitung quote target** dari `quotes.py` (bid di sekitar mid book ± spread)
3. **GUARDRAIL RUMUS** - validasi sebelum order (lihat bagian berikut)
4. **Eksekusi**: lolos → `maker_executor` place/cancel; ditolak → skip
5. **Fill masuk** (WS user) → update inventori → kembali ke langkah 1

---

## Guardrail Rumus (Inti V3)

Sebelum **tiap** bid dipasang, proyeksikan posisi seandainya bid itu terisi, lalu uji dengan `pnl_formula`.

### Formula Kunci

```python
# Modal total
modal = Su * Pu + Sd * Pd

# PnL jika settle
PnL_Up = Su - modal
PnL_Down = Sd - modal

# Worst case (risk-free test)
worst_case = min(Su, Sd) - modal

# Spread pasangan (laba dari pair)
sum_price = Pu + Pd
spread_pair = min(Su, Sd) * (1 - sum_price)

# Imbalance (exposure arah)
imbalance = abs(Su - Sd)
```

### Keputusan Guardrail

```python
def izinkan_bid(sisi, p, q, inv, cfg):
    # Proyeksi posisi pasca-fill
    Su, Sd = inv.su, inv.sd
    Pu, Pd = inv.pu, inv.pd
    
    if sisi == "UP":
        Su = inv.su + q
        Pu = (inv.cost_u + q * p) / Su
    else:
        Sd = inv.sd + q
        Pd = (inv.cost_d + q * p) / Sd

    wc, risk_free = worst_case(Su, Pu, Sd, Pd)
    sum_price = Pu + Pd
    imbalance = abs(Su - Sd)

    # Cap universal
    if imbalance > cfg.max_imbalance:
        return False, "imbalance terlalu besar"
    
    # Mode-specific
    if cfg.mode == "risk_free_only" and not risk_free:
        return False, "bukan risk-free"
    
    if cfg.mode == "spread_positive" and sum_price >= 1:
        return False, "Pu+Pd >= 1 (pasangan rugi)"
    
    return True, "ok"
```

### Mode Guardrail

| Mode | Syarat | Risiko | Penggunaan |
|------|--------|--------|------------|
| `risk_free_only` | `worst_case >= 0` | Minimal (bebas rugi) | **WAJIB untuk live** |
| `spread_positive` | `Pu+Pd < 1` | Sedang (masih ada imbalance) | Paper testing |
| `off` | Tidak ada | Tinggi (seperti Bonereaper) | **DILARANG live** |

> ⚠️ **Peringatan**: Dari analisis 80.188 fill Bonereaper, hanya **14,6% market yang risk-free**. Mode `off` meniru perilaku ini dan dapat menyebabkan kerugian besar.

---

## Profil Waktu Eksekusi

Data empiris dari 80.188 fill menunjukkan pola agresivitas yang berubah terhadap waktu:

| Detik ke Expiry | Fill Count | Maker % | Taker % | Fase |
|-----------------|------------|---------|---------|------|
| **295-300 (buka)** | 1.545 | 18% | **82%** | **TAKER agresif** - seed posisi |
| 240-295 | 14.928 | 54% | 46% | Campur, mulai maker |
| 180-240 | 16.298 | 61% | 39% | Maker-dominan |
| 120-180 | 15.313 | 61% | 39% | Maker-dominan |
| 60-120 | 16.003 | 66% | 34% | Maker naik |
| 30-60 | 8.872 | 77% | 23% | Maker |
| 15-30 | 4.582 | 80% | 20% | Maker |
| **0-15 (akhir)** | 1.557 | **97%** | 3% | **MAKER murni** |
| <0 (settle) | 1.090 | 100% | 0% | Pasif total |

### Implikasi untuk V3

```yaml
schedule:
  taker_until_s: 295           # Di atas ini boleh taker (seed)
  maker_only_below_s: 60       # Di bawah ini maker-only
  taper_size_below_s: 15       # Kecilkan size di detik akhir
  taker_open_max: 0.56         # Peluang taker maksimum saat buka
```

**Logika fase:**
- `t > 295s`: Izinkan TAKER (rebut posisi awal cepat)
- `60s < t ≤ 295s`: MAKER-dominan (quote pasif dua sisi)
- `t ≤ 60s`: MAKER-only (haram menyeberang spread)
- `t ≤ 15s`: MAKER-only + size mengecil (cuma tangkap cash-out)

---

## Harga Masuk Dinamis

Harga bid **tidak statis** - dihitung dari tiga batas:

### 1. Batas Rumus (jaga `Pu+Pd < 1`)

```python
p_bid_UP_max   = 1 - Pd - margin      # Supaya Pu' + Pd tetap < 1
p_bid_DOWN_max = 1 - Pu - margin
```

**Contoh bahaya**: Jika sudah pegang Up avg 0.05, beli Down @ 0.98 → `Pu+Pd = 1.03 > 1` → **pasangan rugi**.

### 2. Batas Saldo (capital/bankroll)

```python
size_bid = f(saldo_tersedia, max_exposure, harga)
budget_sim  = capital_awal - reserve - modal_terkunci
budget_live = min(budget_sim, saldo_venue - order_terbuka)
```

### 3. Batas Imbalance + Waktu

```python
if |Su - Sd| ≈ max_imbalance di sisi X:
    hanya bid sisi X di harga jauh lebih murah

if mendekati expiry:
    ikuti book ke ekstrem, TAPI tetap ≤ cap rumus
```

### Harga Final

```python
def harga_bid(sisi, book, inv, saldo, cfg):
    p_target = book.mid_bid(sisi)                    # Dari quotes.py
    p_cap    = 1 - inv.p_lawan(sisi) - cfg.margin    # Batas rumus
    p        = min(p_target, p_cap)                  # Jangan langgar rumus
    size     = size_dari_saldo(saldo, p, cfg)        # Batas bankroll
    
    if size <= 0 or inv.imbalance(sisi) >= cfg.max_imbalance:
        return None                                  # Skip
    
    return p, size
```

---

## Struktur Folder Target V3

```
src/
├── api/                          [BARU] FastAPI control plane
│   ├── __init__.py
│   ├── app.py                    create_app(); pasang router
│   ├── lifespan.py               startup/shutdown aman
│   ├── dependencies.py           ambil RuntimeRegistry + auth
│   ├── errors.py                 domain error → HTTP response
│   ├── schemas/
│   │   ├── common.py             timestamp, pagination
│   │   ├── market.py             respons market, book, quote
│   │   ├── position.py           Su/Sd/Pu/Pd, worst_case
│   │   └── control.py            validasi pause/resume/reset
│   └── routers/
│       ├── health.py             /health/live, /health/ready
│       ├── markets.py            GET /v1/markets, /v1/markets/{slug}
│       ├── positions.py          GET /v1/positions
│       ├── control.py            POST command aman
│       ├── config.py             GET config + reload
│       ├── metrics.py            GET /metrics Prometheus
│       └── dashboard_ws.py       WS stream snapshot
│
├── runtime/                      [BARU] orkestrasi dan state
│   ├── __init__.py
│   ├── events.py                 BookEvent, FillEvent, WorkerCommand
│   ├── snapshots.py              MarketSnapshot immutable
│   ├── registry.py               registry worker + publish snapshot
│   ├── supervisor.py             buat, awasi, restart worker
│   ├── market_worker.py          satu coroutine per market
│   ├── commands.py               antrian command + idempotency
│   └── preflight_service.py      validasi config + probe dana
│
├── mm/                           Inti strategi (tanpa FastAPI/I/O)
│   ├── pnl_formula.py            [PINDAH] modal, PnL, worst_case
│   ├── paired_inventory.py       [BARU] Su/Sd/cost_up/cost_down
│   ├── guardrail.py              [BARU] allow/reject candidate
│   ├── runner.py                 [UBAH] MakerRunner
│   ├── inventory.py              [TETAP] akuntansi net V2
│   ├── quotes.py                 [TETAP] harga/size target
│   ├── risk.py                   [TETAP] kill, exposure, stale
│   ├── maker_executor.py         [TETAP] reconcile/cancel
│   └── ...                       (modul lain tetap ada)
│
├── infra/                        [BARU] adapter I/O
│   ├── __init__.py
│   ├── polymarket/
│   │   ├── book.py               [PINDAH] OrderBook, parser
│   │   ├── market_stream.py      [BARU] WS market → BookEvent
│   │   ├── user_stream.py        [PINDAH] WS user → FillEvent
│   │   ├── market_catalog.py     [PINDAH] discovery slug/token
│   │   └── clob_gateway.py       [PINDAH] REST GTC/post-only
│   ├── storage/
│   │   ├── event_journal.py      JSONL audit append
│   │   └── config_store.py       baca config + redaksi secret
│   └── onchain/
│       └── reconciliation.py     panggil src/onchain/*
│
├── observability/                [BARU] logging + metrics
│   ├── logging.py                log JSON + correlation id
│   └── metrics.py                Prometheus counter/histogram
│
└── tui/
    └── dashboard.py              [PINDAH] Rich terminal subscriber

scripts/
├── run_market_maker.py           [UBAH] CLI tipis → supervisor
├── simulate_paired_orders.py     [SUDAH ADA] REPL simulasi
└── ...                           (script lain disesuaikan)
```

---

## API Endpoints V3

Semua endpoint di bawah `/v1` kecuali health dan metrics.

| Method | Path | Deskripsi | Catatan |
|--------|------|-----------|---------|
| GET | `/health/live` | Process hidup | Tidak jamin aman trading |
| GET | `/health/ready` | Preflight + worker siap | 503 bila fail-closed |
| GET | `/v1/markets` | Ringkasan semua worker | Hanya snapshot |
| GET | `/v1/markets/{slug}` | Detail market | Token sensitif disensor |
| GET | `/v1/positions` | Su/Sd/Pu/Pd, worst_case | Dari PairedInventory |
| GET | `/v1/guardrail/rejects` | Reject terbaru | Buffer terbatas |
| GET | `/v1/config` | Config tanpa secret | Read-only |
| POST | `/v1/config/reload` | Reload parameter aman | Tidak ubah credential |
| POST | `/v1/markets/{slug}/pause` | Pause + cancel all | 202 + command_id |
| POST | `/v1/markets/{slug}/resume` | Resume setelah preflight | Gagal tetap pause |
| POST | `/v1/markets/{slug}/reset-session` | Reset kill/funding halt | Butuh auth |
| POST | `/v1/markets/{slug}/cancel-orders` | Cancel eksplisit | 202 + command_id |
| WS | `/v1/ws/dashboard` | Stream snapshot | Slow client drop frame lama |
| GET | `/metrics` | Prometheus metrics | Bind privat/auth proxy |

### Contoh Respons `/v1/positions`

```json
{
  "market_slug": "btc-up-down-2024-08-05",
  "Su": 262.00,
  "Sd": 43.99,
  "Pu": 0.139,
  "Pd": 0.725,
  "modal": 68.32,
  "PnL_Up": -36.44,
  "PnL_Down": 11.68,
  "worst_case": -24.33,
  "matched": 43.99,
  "imbalance": 218.01,
  "spread_pair": 5.98,
  "mode": "risk_free_only",
  "is_risk_free": false
}
```

---

## Konfigurasi V3 Wajib

```yaml
market_maker:
  guardrail:
    mode: risk_free_only          # WAJIB untuk live!
    max_imbalance_shares: 14
    pair_margin: 0.02
  
  capital:
    session_capital_usd: 20       # Batas modal sesi
    reserve_usd: 4                # Dana tidak terpakai
    max_order_usd: 2.50           # Batas satu leg BUY
    min_shares: 5                 # Minimum shares
  
  schedule:
    taker_until_s: 295            # Seed posisi awal
    maker_only_below_s: 60        # Maker-only dekat expiry
    taper_size_below_s: 15        # Kecilkan size akhir
    taker_open_max: 0.56          # Max agresivitas buka
  
  runtime:
    book_debounce_ms: 25
    fill_queue_max: 1000
    reconnect_max_delay_s: 10
    shutdown_timeout_s: 15
  
  api:
    enabled: true
    host: 127.0.0.1               # Bind lokal saja
    port: 8000

# Environment variables (JANGAN di config.json!)
BOT_API_TOKEN=<rahasia>
```

---

## Rencana Migrasi 5 Tahap

| Tahap | Fokus | Kriteria Selesai |
|-------|-------|------------------|
| **0. Fondasi** | `pnl_formula.py`, `paired_inventory.py`, `guardrail.py` | Unit test rumus lulus |
| **1. Adapter** | Pindah ke `infra/polymarket/` | Script lama masih jalan |
| **2. WebSocket** | `market_stream.py`, `user_stream.py` WS | Mock reconnect/desync lulus |
| **3. Worker** | `market_worker.py`, `supervisor.py` | Paper mode pakai worker baru |
| **4. FastAPI** | `api/*`, observability | TestClient lifecycle lulus |
| **5. Canary** | Live ukuran minimum | Dashboard + journal konsisten |

### Prinsip Migrasi

- ✅ **Tidak memutus V2** - scripts/run_market_maker.py tetap entry point selama transisi
- ✅ **Shadow verification** - V3 jalan paralel dengan V2 untuk validasi
- ✅ **Fail-closed** - Error tak dikenal → pause + cancel all + alarm

---

## Peringatan Penting

### ⚠️ Mode `off` DILARANG untuk Live

Dari analisis 80.188 fill Bonereaper:
- Hanya **14,6% market yang risk-free** (`worst_case >= 0`)
- **46,9% market punya `Pu+Pd < 1`** (pasangan untung, tapi belum tentu aman)
- **85,4% market berpotensi rugi besar** jika outcome salah

Mode `off` meniru Bonereaper apa adanya dan dapat menyebabkan:
- Kerugian -$739 pada market tunggal (data nyata)
- Imbalance tak terkendali (>200 shares satu sisi)
- PnL volatil seperti +$1.643 / -$739

### ✅ Best Practice V3

1. **Selalu gunakan `risk_free_only` untuk live**
2. **Monitor `worst_case` di dashboard** - harus >= 0
3. **Batasi `imbalance`** - default max 14 shares
4. **Jangan over-leverage** - gunakan `session_capital_usd`
5. **Audit via `/v1/positions`** - cek `spread_pair` vs `imbalance`

---

## Referensi

- [Positions & Tokens Polymarket](https://docs.polymarket.com/concepts/positions-tokens)
- [Order Lifecycle Polymarket](https://docs.polymarket.com/concepts/order-lifecycle)
- [Taker Delay 250ms BTC](https://clob.polymarket.com/clob-markets/{condition_id})
- [Analisis Akumulasi Bonereaper](./Analisis-akumulasi-Bonereaper.md)

---

**Dokumen ini adalah sumber kebenaran tunggal untuk migrasi V3.** Semua dokumentasi lain harus mengacu ke sini.
