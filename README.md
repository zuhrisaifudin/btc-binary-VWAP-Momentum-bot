# Bot Polymarket BTC Binary — Arsitektur V3

## 📘 Dokumentasi Utama

**Acuan tunggal arsitektur:** [Arsitektur Bot v3 — FastAPI Control Plane + Worker Event-Driven](Arsitektur%20Bot%20v3%20—%20FastAPI%20Control%20Plane%20+%20Worker%20Event-Driven)

> ⚠️ **Dokumen ini adalah rancangan target V3**, bukan klaim bahwa semua file sudah ada. Fokus pada migrasi bertahap tanpa memutus bot V2 yang sedang berjalan.

---

## 🚀 Ringkasan Migrasi V2 → V3

### Perbedaan Utama

| Aspek | V2 (Sekarang) | **V3 (Target)** |
|---|---|---|
| Data Fill | REST-poll (lag 100ms–1s) | **WebSocket** (~50–150ms) |
| Order Book | REST read | **WS book in-memory** |
| Cek Pra-Order | Risk/inventory | **+ Guardrail rumus** `worst_case`/`Pu+Pd<1` |
| Arsitektur | Monolitik | **FastAPI Control Plane + Worker Event-Driven** |
| Status | Live-ready | Rancangan (migrasi bertahap) |

### Komponen Baru V3

```
infra/polymarket/market_stream.py  [BARU]  WS book → book in-memory
infra/polymarket/user_stream.py    [PINDAH/UBAH] WS fill + fallback REST
runtime/market_worker.py           [BARU]  Event loop per market + single writer
mm/guardrail.py                    [BARU]  Keputusan order dari rumus PnL
mm/pnl_formula.py                  [PINDAH] Matematika murni yang dapat diimpor
api/                               [BARU]  FastAPI control plane + WebSocket UI
```

---

## 📐 Arsitektur V3

### Filosofi Desain

1. **Jalur eksekusi WebSocket yang cepat dan fail-closed**
2. **Guardrail `pnl_formula` sebelum order menambah posisi**
3. **FastAPI sebagai control plane produksi tanpa menjadikan HTTP sebagai jalur trading**

### Flow Utama (Event Loop)

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

**Langkah per event:**
1. Baca inventori: `Su, Sd, Pu, Pd`
2. Hitung quote target dari `quotes.py`
3. **GUARDRAIL RUMUS** (inti keamanan)
4. Eksekusi yang lolos → `maker_executor`
5. Fill masuk → update inventori → ulang langkah 1

---

## 🔒 Guardrail Rumus: Inti Keamanan

Sebelum tiap bid dipasang, proyeksikan posisi seandainya bid itu keisi, lalu uji dengan `pnl_formula`.

### Pseudocode Keputusan

```python
def izinkan_bid(sisi, p, q, inv, cfg):
    Su, Sd = inv.su, inv.sd
    Pu, Pd = inv.pu, inv.pd
    
    if sisi == "UP":
        Su = inv.su + q; Pu = (inv.cost_u + q*p) / Su
    else:
        Sd = inv.sd + q; Pd = (inv.cost_d + q*p) / Sd

    wc, risk_free = worst_case(Su, Pu, Sd, Pd)
    sum_price = Pu + Pd
    imbalance = abs(Su - Sd)

    if imbalance > cfg.max_imbalance:
        return False, "imbalance terlalu besar"
    if cfg.mode == "risk_free_only" and not risk_free:
        return False, "bukan risk-free"
    if cfg.mode == "spread_positive" and sum_price >= 1:
        return False, "Pu+Pd >= 1 (pasangan rugi)"
    return True, "ok"
```

### Mode Guardrail

| Mode | Kondisi PLACE | Keterangan |
|---|---|---|
| `risk_free_only` | `worst' ≥ 0` | Paling ketat, tolak order yang bisa rugi apa pun hasilnya |
| `spread_positive` | `sum_price' < 1` | Pasangan untung, tapi masih bisa rugi jika imbalance besar |
| `off` | Selalu | **HANYA untuk replay/analisis**, tidak boleh live |

---

## 💰 Bagaimana Bot V3 Menghasilkan Uang

Sumber laba utama adalah membeli **dua sisi pasangan** dengan biaya gabungan di bawah $1:

```text
Su, Sd     = share Up dan Down terisi
Pu, Pd     = rata-rata harga beli
C          = modal = Su × Pu + Sd × Pd
M          = min(Su, Sd)         # share berpasangan
D          = |Su - Sd|           # share satu sisi tersisa
laba_pasangan = M × (1 - Pu - Pd)  # spread pair
worst_case    = M - C              # risiko minimum
```

Jika `Pu + Pd < 1` dan `M > 0`, setiap share pasangan dibeli kurang dari $1 menghasilkan $1 saat di-merge/settle.

---

## ⏱ Profil Waktu: Kapan TAKER, Kapan MAKER

Data dari 80.188 fill nyata:

| Detik ke Expiry | Maker% | Taker% | Fase |
|---|---|---|---|
| **295–300 (buka)** | 18% | **82%** | **TAKER agresif** — seed posisi cepat |
| 240–295 | 54% | 46% | Campur, mulai maker |
| 180–240 | 61% | 39% | Maker-dominan |
| 120–180 | 61% | 39% | Maker-dominan |
| 60–120 | 66% | 34% | Maker naik |
| 30–60 | 77% | 23% | Maker |
| 15–30 | 80% | 20% | Maker |
| **0–15 (akhir)** | **97%** | 3% | **MAKER murni** — likuiditas keluar |

**Implikasi V3:**
```
t > 295s          → Izinkan TAKER (seed)
60s < t ≤ 295s    → MAKER-dominan
t ≤ 60s           → MAKER-only (haram menyeberang spread)
t ≤ 15s           → MAKER-only, size mengecil
```

---

## 🌐 FastAPI Control Plane

### API Endpoints V3

| Method | Path | Tanggung Jawab |
|---|---|---|
| GET | /health/live | Process hidup |
| GET | /health/ready | Preflight, worker, feed siap |
| GET | /v1/markets | Ringkasan semua worker |
| GET | /v1/markets/{slug} | Book, quote, status |
| GET | /v1/positions | Su/Sd/Pu/Pd, PnL, worst_case, matched, imbalance |
| GET | /v1/config | Konfigurasi tanpa secret |
| POST | /v1/config/reload | Reload parameter aman |
| POST | /v1/markets/{slug}/pause | Pause + cancel all |
| POST | /v1/markets/{slug}/resume | Resume setelah preflight |
| WS | /v1/ws/dashboard | Push snapshot terbaru |
| GET | /metrics | Prometheus metrics |

**Tidak ada endpoint** place-order, flatten, transfer dana, atau switch paper→live.

---

## 📁 Struktur Folder Target

```
src/
├── api/                                            [BARU]
│   ├── app.py, lifespan.py, dependencies.py
│   ├── schemas/ (market, position, control)
│   └── routers/ (health, markets, positions, control, config, metrics, dashboard_ws)
├── runtime/                                        [BARU]
│   ├── events.py, snapshots.py, registry.py
│   ├── supervisor.py, market_worker.py
│   ├── commands.py, preflight_service.py
├── mm/                                             inti strategi
│   ├── pnl_formula.py [PINDAH], paired_inventory.py [BARU]
│   ├── guardrail.py [BARU], runner.py [UBAH]
│   ├── quotes.py, risk.py, maker_executor.py [TETAP]
│   └── ... modul lainnya
├── infra/                                          [BARU] adapter I/O
│   └── polymarket/
│       ├── book.py, market_stream.py, user_stream.py
│       ├── market_catalog.py, clob_gateway.py
│   └── storage/
│       ├── event_journal.py, config_store.py
├── observability/                                   [BARU]
│   ├── logging.py, metrics.py
└── tui/
    └── dashboard.py [PINDAH bertahap]

scripts/
├── run_market_maker.py [UBAH jadi CLI tipis]
├── simulate_paired_orders.py [SUDAH ADA]
└── test_*.py [test suite baru]
```

---

## 🔄 Rencana Migrasi Bertahap

| Tahap | Fokus | Kriteria Selesai |
|---|---|---|
| 0 | Fondasi murni (pnl_formula, paired_inventory, guardrail) | Unit test lulus |
| 1 | Pisahkan adapter ke infra/polymarket | Scripts lama stabil |
| 2 | WebSocket & recovery (market_stream, user_stream) | Mock reconnect/desync lulus |
| 3 | Worker (market_worker, supervisor) | Paper mode pakai worker baru |
| 4 | FastAPI (api/*, observability/*) | TestClient lifecycle/control/WS lulus |
| 5 | Canary (paper → live minimal) | Dashboard, journal, reconciliation konsisten |

**Selama tahap 1–4**, `scripts/run_market_maker.py` tetap entry point kompatibel.

---

## ⚙️ Konfigurasi V3

```yaml
market_maker:
  guardrail:
    mode: risk_free_only       # risk_free_only | spread_positive | off (paper)
    max_imbalance_shares: 14
    pair_margin: 0.02
  capital:
    session_capital_usd: 20
    reserve_usd: 4
    max_order_usd: 2.50
    min_shares: 5
  runtime:
    book_debounce_ms: 25
    fill_queue_max: 1_000
    reconnect_max_delay_s: 10
    shutdown_timeout_s: 15
  api:
    enabled: true
    host: 127.0.0.1
    port: 8000

# Environment (TIDAK BOLEH di config.json):
BOT_API_TOKEN=...
```

---

## ⚠️ Peringatan Penting

1. **Mode `off`** hanya untuk replay/analisis, tidak boleh live
2. **Fill tidak boleh hilang** — fail-closed jika queue penuh
3. **API tidak boleh mengeksekusi CLOB** langsung
4. **Satu Uvicorn worker per akun** — jangan --workers > 1
5. **Credential tidak boleh masuk log** atau config.json
6. **Post-only wajib** untuk jamin maker fee 0 + rebate
7. **Taker delay 250 ms** di btc-5m — pakai seminimal mungkin

---

## 📞 Referensi

- **Dokumen Lengkap:** [Arsitektur Bot v3](Arsitektur%20Bot%20v3%20—%20FastAPI%20Control%20Plane%20+%20Worker%20Event-Driven)
- **Polymarket Docs:** https://docs.polymarket.com/
- **Telegram:** [@terauss](https://t.me/terauss)

---

**Status:** Rancangan target V3. Migrasi dilakukan bertahap tanpa memutus bot V2.
