# Roadmap Perbaikan — BTC VWAP/Momentum Bot

> Dokumen ini merangkum temuan analisis codebase dan rencana perbaikan bertahap.
> Urutan: **Keamanan → akurasi uang → eksekusi → kualitas kode → strategi.**
> Jangan mengembangkan strategi baru sebelum P&L yang dicatat bisa dipercaya,
> karena semua keputusan strategi selama ini didasarkan pada metrik yang error.

---

## Daftar Isi
- [FASE 0 — Mitigasi Insiden Keamanan](#-fase-0--mitigasi-insiden-keamanan-hari-ini-2-jam--tunggu-rotasi)
- [FASE 1 — Akurasi P&L & Metrik](#-fase-1--akurasi-pnl--metrik-05-hari)
- [FASE 2 — Eksekusi & Risk Guard](#-fase-2--eksekusi--risk-guard-05-hari)
- [FASE 3 — Hygiene & Fondasi Test](#-fase-3--hygiene--fondasi-test-1-hari)
- [FASE 4 — Strategi & Pengembangan](#-fase-4--strategi--pengembangan-setelah-fase-1-terbukti)
- [Ringkasan Timeline](#ringkasan-timeline)

---

## 🚨 FASE 0 — Mitigasi Insiden Keamanan (Hari Ini, ~2 jam + tunggu rotasi)

**Masalah:** `.env` berisi private key & API secret aktif ter-commit ke git
(kemungkinan ter-push ke `PolyBullLabs/...`). `.gitignore` hanya memuat
`__pycache__/` dan `*.pyc`.

### Langkah
1. **Rotasi semua kredensial** (anggap sudah bocor, tidak ada jalan lain):
   - `PRIVATE_KEY` → buat wallet Polygon **baru**, pindahkan semua USDC/POL
     ke wallet baru. Wallet lama dianggap kompromi permanen.
   - Regenerasi API CLOB (key/secret/passphrase) di pengaturan Polymarket.
   - Revoke + buat ulang Telegram bot token via @BotFather.
   - Rotate Alchemy API key di dashboard Alchemy.
2. **Perbaiki `.gitignore`** — tambahkan:
   ```
   .env
   logs/
   *.pyc
   __pycache__/
   ```
3. **Hentikan tracking** file sensitif:
   ```bash
   git rm --cached .env
   git rm --cached -r logs __pycache__ src/__pycache__
   ```
4. **Bersihkan riwayat git** (karena secret ada di history, `git rm --cached`
   saja tidak cukup):
   ```bash
   # pakai git-filter-repo (lebih aman daripada BFG)
   pip install git-filter-repo
   git filter-repo --path .env --invert-paths
   git filter-repo --path logs --invert-paths
   ```
   ⚠️ Ini **menulis ulang history** → force-push ke remote dan koordinasikan
   dengan siapa pun yang punya clone.
5. Cek apakah repo pernah public/push ke GitHub. Jika ya, rotasi (langkah 1)
   **wajib sudah selesai** sebelum langkah 4.

### Kriteria Selesai
- [ ] Semua kredensial baru berfungsi, kredensial lama di-revoke.
- [ ] `git status` tidak menampilkan `.env` / `logs/` / `*.pyc`.
- [ ] `git log --all -- .env` kosong setelah rewrite history.
- [ ] Remote di-force-push.

---

## 🔴 FASE 1 — Akurasi P&L & Metrik (~0.5 hari)

**Masalah:** P&L dicatat dari `last_price` 10 detik sebelum expiry dengan
threshold `>= 0.70` (`main.py:444`), bukan resolusi sebenarnya. Semua statistik
historis & simulasi jadi tidak valid.

### Langkah
1. **Tambah field status pending-close** pada `Position`/`TradeRecord` — posisi
   ditandai "awaiting resolution" saat market berakhir, bukan langsung
   `close_position(final_price)`.
2. **Polling resolusi market** via Gamma API (`market.closed == true` + baca
   outcome) di method baru `resolve_position()`. Jadwalkan poll tiap ~5–10
   detik setelah expiry.
3. **Hitung P&L dari outcome sebenarnya**: menang → payout
   `$1 × contracts`; kalah → `$0`.
4. **Backfill log lama** (opsional): tandai trade existing di `trading_log.json`
   sebagai `resolution_source: "preliminary_last_price"` agar tidak dicampur
   dengan data yang sudah akurat.
5. **Pisahkan** P&L realisasi (sudah di-redeem) vs P&L tercatat (resolusi
   diketahui, tunggu redeem) — auto_redeemer update status.

### Kriteria Selesai
- [ ] `close_position` dipanggil hanya setelah `market.closed == true`.
- [ ] Unit test: trade entry $0.80 → market MENANG → P&L =
      `contracts × (1 - 0.80)` (bukan tergantung last_price).
- [ ] Unit test: market KALAH → P&L = `-contracts × 0.80`.
- [ ] `trading_log.json` mencatat `resolution_source` per trade.

---

## 🟠 FASE 2 — Eksekusi & Risk Guard (~0.5 hari)

**Masalah:** trap order < minimum $1 pasti gagal di live;
`daily_stop_loss` hardcoded `-50.0` (`main.py:327`); dead code
`_register_hedge_ws_handler` (`main.py:2209`); `min_momentum_5s` tidak
berfungsi.

### Langkah
1. **Fix minimum order trap** — pilih salah satu:
   - (a) Naikkan `dual_position.total_budget_usd` ke ≥ $2 × alokasi trap ≥ $1
     (mis. budget $12, trap 10% = $1.20).
   - (b) Tambah guard di `execute_dual_position`: jika
     `trap_budget < MIN_ORDER_USD` → skip trap + log warning eksplisit
     (bukan diam-diam gagal di CLOB).
   - (c) Validasi pre-trade: `validate_config` menolak config trap yang tidak
     mungkin fill.
2. **`daily_stop_loss` dari config**:
   - Tambah `entry.daily_stop_loss_usd` (default `-5.0` untuk bet kecil) di
     `config.json`, `EntryConfig`, dan `load_config`.
   - Set `self.stats.daily_stop_loss = config.entry.daily_stop_loss_usd` di
     `initialize()`.
3. **Hapus dead code** `_register_hedge_ws_handler` (`main.py:2209`) + komentar
   menyesatkan di `:2397`. Jika hedge GTD akan dipakai lagi, implementasikan
   sebagai task terpisah yang benar (bukan monkey-patch `user_ws._on_trade`).
4. **Putuskan `min_momentum_5s`**: kalau Trap Play memang sengaja abaikan
   momentum, hapus parameternya dari config + docs agar tidak menyesatkan.
   Kalau ingin aktif, benar-benar pakai di `mom_ok`.

### Kriteria Selesai
- [ ] Tidak ada order live yang dikirim di bawah $1 tanpa warning/handling
      eksplisit.
- [ ] `daily_stop_loss_usd` bisa diatur dari config dan terbukti memblok entry
      di test.
- [ ] `grep -n "_register_hedge_ws_handler" main.py` → kosong.
- [ ] `min_momentum_5s` konsisten: dipakai atau dihapus.

---

## 🟡 FASE 3 — Hygiene & Fondasi Test (~1 hari)

**Masalah:** file log/pyc ter-commit; nol test; `main.py` 2.480 baris;
bare `except:` di blok cleanup.

### Langkah
1. **Selesaikan `.gitignore`** (lanjutan Fase 0) + `git rm --cached` sisa file.
2. **Buat struktur test** (`tests/`, pakai `pytest`):
   ```
   tests/
   ├── test_indicators.py     # calc_vwap, calc_momentum (None case), calc_zscore, calc_deviation
   ├── test_pnl.py            # close_position: win/loss/hedge/trap scenarios
   ├── test_sizing.py         # _calculate_contracts, _validate_order_size, minimum $1
   ├── test_winrate_table.py  # get_winrate edge cases, bin clamping
   └── test_config_validation.py
   ```
3. **Ekstrak `main.py`** jadi modul (tanpa ubah perilaku):
   - `src/indicators.py` ← `IndicatorCalculator`, `WinRateTable`, `Trade`
   - `src/stats.py` ← `TradingStats`, `Position`, `TradeRecord`, `MarketState`
   - `src/dashboard.py` ← `Dashboard`, formatter
   - `src/chainlink_client.py` ← `ChainlinkPriceClient`
   - `src/ws_client.py` ← `WebSocketClient`
   - `main.py` tinggal `LiveTradingBot` + `main()`.
4. **Ganti bare `except:`** → `except Exception:` di semua blok cleanup
   (`run_session`, `run`).
5. **Perkuat `validate_config`**:
   - `main_allocation_pct + trap_allocation_pct == 1.0`
   - `min_elapsed_sec + no_entry_before_end_sec < duration_sec`
     (window entry > 0)
   - `max_trap_price` relatif `max_price` masuk akal.

### Kriteria Selesai
- [ ] `pytest` green, coverage ≥ 70% untuk logika P&L & indikator.
- [ ] `main.py` < ~500 baris.
- [ ] `grep -n "except:" main.py` → kosong (semua `except Exception:`).
- [ ] Config tidak valid ditolak dengan pesan jelas.

---

## 🔵 FASE 4 — Strategi & Pengembangan (setelah Fase 1 terbukti)

**Hanya lanjut setelah P&L akurat (Fase 1)**, karena evaluasi strategi butuh
data valid.

### Opsi pengembangan (pilih berdasarkan data)
1. **Evaluasi ulang Trap Play** — dengan P&L akurat, hitung: apakah trap 10%
   benar-benar meningkatkan EV atau hanya mengurangi profit? Bandingkan
   win-rate & EV dual vs single.
2. **Slippage tracking** — catat `websocket_price` vs `avg_fill_price` per
   trade untuk mengukur edge yang hilang.
3. **Parameter sweep di simulasi** — jalankan beberapa preset config di sim
   mode, bandingkan EV.
4. **Recovery timeout WS** — `ws_recovery_timeout_sec` ada di config tapi
   perlu verifikasi benar dipakai.
5. **Monitoring** — alert Telegram saat daily_stop_loss hit, WS disconnect
   lama, atau fill rate turun.

### Kriteria Selesai
- [ ] Keputusan strategi (pertahankan/ubah Trap Play) didukung data P&L akurat
      minimal 100 trade.
- [ ] Setiap parameter config punya dokumentasi + rentang wajar di `CONFIG.md`.

---

## Ringkasan Timeline

| Fase | Durasi | Bisa berhenti setelahnya? | Risiko tersisa |
|---|---|---|---|
| 0 — Keamanan | 2 jam | ✅ bot aman dijalankan | P&L masih tidak akurat |
| 1 — Akurasi P&L | 0.5 hari | ✅ metrik bisa dipercaya | trap mungkin masih gagal live |
| 2 — Eksekusi & risk | 0.5 hari | ✅ live trading sehat | kode masih berantakan |
| 3 — Hygiene & test | 1 hari | ✅ maintainable | — |
| 4 — Strategi | variabel | ✅ data-driven | — |

**Total Fase 0–3: ~2 hari kerja.** Jangan lanjut ke Fase 4 sebelum Fase 1
selesai — strategi yang dioptimasi dari metrik salah akan membuat kerugian
lebih cepat, bukan lebih lambat.

---

## Catatan Eksekusi
- Untuk rotasi secret di Fase 0, sebagian langkah (pindah dana, regenerasi API
  Polymarket, revoke Telegram) harus dilakukan manual di UI. Bagian
  git/gitignore/history bisa di-handle dari sisi kode.
- Tiap fase dirancang independen — berhenti di akhir fase mana pun tetap
  meninggalkan bot dalam keadaan lebih baik dari sebelumnya.
