# Dokumentasi Bot Polymarket BTC Binary — Arsitektur V3

## 📚 Daftar Dokumen

Semua dokumentasi mengacu pada **Arsitektur Bot v3 — FastAPI Control Plane + Worker Event-Driven** sebagai acuan tunggal.

### Dokumen Utama

| Dokumen | Deskripsi | Status |
|---|---|---|
| [README.md](../README.md) | Panduan utama migrasi V2→V3 | ✅ Updated V3 |
| [Arsitektur Bot v3](../Arsitektur%20Bot%20v3%20—%20FastAPI%20Control%20Plane%20+%20Worker%20Event-Driven) | Spesifikasi lengkap arsitektur V3 | ✅ Referensi utama |
| [CONFIG.md](../CONFIG.md) | Panduan konfigurasi (akan diupdate untuk V3) | ⏳ To Update |
| GUIDELINE_DUAL_SIDE_REGIME.md | Pedoman dual-side regime (V2) | ⚠️ Legacy V2 |
| IMPROVEMENT_PLAN.md | Rencana improvement (akan disesuaikan V3) | ⏳ To Update |
| PROMPT_polymarket_btc_5m_dual_side_scaling.md | Prompt engineering (V2) | ⚠️ Legacy V2 |
| dual_side_scaling_usage.md | Cara pakai dual-side scaling (V2) | ⚠️ Legacy V2 |

---

## 🎯 Migrasi Dokumentasi V2 → V3

### Dokumen yang Perlu Diupdate

1. **CONFIG.md** — Menambahkan parameter guardrail, runtime, dan API V3
2. **GUIDELINE_DUAL_SIDE_REGIME.md** — Mengganti dengan guardrail rumus V3
3. **IMPROVEMENT_PLAN.md** — Menyesuaikan dengan roadmap migrasi V3
4. **dual_side_scaling_usage.md** — Mengganti dengan panduan maker/taker V3

### Dokumen Legacy (Tidak Relevan untuk V3)

- `PROMPT_polymarket_btc_5m_dual_side_scaling.md` — Strategi V2 sudah tidak dipakai
- `dual_side_scaling_usage.md` — Akan diganti dengan panduan profil waktu V3

---

## 📐 Ringkasan Arsitektur V3

### Komponen Utama

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Control Plane                     │
│  - HTTP endpoints (/v1/*)                                    │
│  - WebSocket dashboard                                       │
│  - Command dispatch (pause/resume/reset)                     │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   Runtime Supervisor                         │
│  - Lifecycle management                                      │
│  - Worker orchestration                                      │
│  - Preflight validation                                      │
└─────────────────────────────────────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
    ┌─────────────────┐         ┌─────────────────┐
    │  MarketWorker   │         │  MarketWorker   │
    │  (BTC 5m)       │         │  (BTC 15m)      │
    │  - Book in-mem  │         │  - Book in-mem  │
    │  - Inventory    │         │  - Inventory    │
    │  - Guardrail    │         │  - Guardrail    │
    │  - Quote engine │         │  - Quote engine │
    └────────┬────────┘         └────────┬────────┘
             │                           │
             └───────────┬───────────────┘
                         ▼
            ┌────────────────────────┐
            │   MakerOrderExecutor   │
            │   - REST CLOB          │
            │   - Post-only          │
            └───────────┬────────────┘
                        ▼
            ┌────────────────────────┐
            │    Polymarket CLOB     │
            │    - WS market/book    │
            │    - WS user/fill      │
            │    - REST order        │
            └────────────────────────┘
```

### Flow Event

1. **Book delta** dari WS → update book in-memory
2. **Fill event** dari WS → update PairedInventory
3. **Quote engine** hitung target bid/ask
4. **Guardrail** proyeksi posisi pasca-fill → allow/reject
5. **Executor** place/cancel order (REST, post-only)
6. **Snapshot** dipublish ke API/dashboard

---

## 🔒 Guardrail Rumus

Inti keamanan V3: setiap kandidat order diproyeksikan posisi pasca-fill, lalu diuji dengan rumus PnL.

### Mode Guardrail

| Mode | Kondisi | Risiko |
|---|---|---|
| `risk_free_only` | `worst_case ≥ 0` | Paling aman, bebas rugi apa pun hasil |
| `spread_positive` | `Pu + Pd < 1` | Pasangan untung, masih bisa rugi jika imbalance |
| `off` | Selalu | **HANYA replay/analisis**, tidak live |

### Rumus Inti

```text
Su, Sd     = share Up/Down terisi
Pu, Pd     = rata-rata harga beli
C          = Su×Pu + Sd×Pd           # modal
M          = min(Su, Sd)             # share berpasangan
D          = |Su - Sd|               # imbalance
laba_pair  = M × (1 - Pu - Pd)       # spread pasangan
worst_case = M - C                   # risiko minimum
```

---

## ⏱ Profil Waktu Eksekusi

Data empiris dari 80.188 fill:

| Detik ke Expiry | Taker% | Maker% | Aksi |
|---|---|---|---|
| 295–300 (buka) | **82%** | 18% | TAKER agresif — seed posisi |
| 240–295 | 46% | 54% | Campur, mulai maker |
| 180–240 | 39% | 61% | Maker-dominan |
| 120–180 | 39% | 61% | Maker-dominan |
| 60–120 | 34% | 66% | Maker naik |
| 30–60 | 23% | 77% | Maker |
| 15–30 | 20% | 80% | Maker |
| 0–15 (akhir) | 3% | **97%** | MAKER murni — likuiditas keluar |

**Implikasi:** Bot V3 menyesuaikan mode eksekusi berdasarkan waktu ke expiry, bukan konstan.

---

## 🌐 API Endpoints V3

### Health & Readiness

| Endpoint | Deskripsi |
|---|---|
| `GET /health/live` | Process hidup |
| `GET /health/ready` | Siap trading (preflight pass, feed sehat) |

### Market Data

| Endpoint | Deskripsi |
|---|---|
| `GET /v1/markets` | Ringkasan semua worker |
| `GET /v1/markets/{slug}` | Detail market: book, quote, status |
| `GET /v1/positions` | Posisi semua market: Su/Sd/Pu/Pd, PnL, worst_case |

### Control

| Endpoint | Deskripsi |
|---|---|
| `POST /v1/markets/{slug}/pause` | Pause trading + cancel all |
| `POST /v1/markets/{slug}/resume` | Resume setelah preflight |
| `POST /v1/markets/{slug}/reset-session` | Reset kill/funding halt |
| `POST /v1/config/reload` | Reload parameter aman |

### Observability

| Endpoint | Deskripsi |
|---|---|
| `GET /v1/config` | Konfigurasi efektif (tanpa secret) |
| `GET /v1/guardrail/rejects` | Reject terbaru dengan reason |
| `WS /v1/ws/dashboard` | Stream snapshot real-time |
| `GET /metrics` | Prometheus metrics |

---

## 🔄 Roadmap Migrasi

| Tahap | Fokus | Status |
|---|---|---|
| 0 | Fondasi (pnl_formula, paired_inventory, guardrail) | 📝 Planning |
| 1 | Adapter infra/polymarket | 📝 Planning |
| 2 | WebSocket market_stream & user_stream | 📝 Planning |
| 3 | MarketWorker & Supervisor | 📝 Planning |
| 4 | FastAPI control plane | 📝 Planning |
| 5 | Canary deployment | 📝 Planning |

---

## ⚠️ Peringatan Penting

1. **Mode `off`** tidak boleh live
2. **Fill tidak boleh hilang** — fail-closed jika queue penuh
3. **API tidak eksekusi CLOB** langsung
4. **Satu Uvicorn worker per akun**
5. **Credential tidak masuk log**
6. **Post-only wajib** untuk maker fee 0
7. **Taker delay 250 ms** — pakai seminimal mungkin

---

## 📞 Referensi

- **Dokumen Lengkap:** [Arsitektur Bot v3](../Arsitektur%20Bot%20v3%20—%20FastAPI%20Control%20Plane%20+%20Worker%20Event-Driven)
- **Polymarket Docs:** https://docs.polymarket.com/
- **Telegram:** [@terauss](https://t.me/terauss)

---

**Status:** Dokumen ini akan diupdate seiring progres migrasi V3. Acuan utama tetap dokumen arsitektur lengkap.
