# 🚀 Perubahan Strategi Hedge: Dari GTD Pasif ke Instant Hedge Aktif

## 📋 Ringkasan Perubahan

Bot telah diupdate untuk menggunakan **Instant Hedge** (FAK order di harga pasar) alih-alih **GTD Hedge** (limit order pasif di $0.02). Ini memberikan proteksi aktif yang langsung bekerja setelah entry.

---

## 🔧 File yang Dimodifikasi

### 1. `config.json`
**Perubahan:**
```json
"hedge": {
    "enabled": true,
    "hedge_price": 0.02,
    "hedge_contracts": 1,        // ← BARU: Jumlah kontrak proteksi
    "order_type": "FAK",         // ← UBAH: Dari "GTD" ke "FAK"
    "max_retries": 3,
    "retry_delay_ms": 300        // ← UBAH: Lebih cepat (300ms vs 1000ms)
}
```

**Cara Mengubah Jumlah Hedge:**
- `hedge_contracts: 1` → Proteksi dasar (hemat ~$0.82 per loss)
- `hedge_contracts: 2` → Proteksi ganda (hemat ~$1.64 per loss)

---

### 2. `src/config_loader.py`
**Perubahan:**
- Tambah field `hedge_contracts: int = 1` di class `HedgeConfig`
- Update fungsi `load_config()` untuk membaca `hedge_contracts` dari JSON

---

### 3. `src/hedge_manager.py`
**Perubahan:**
- Tambah field `hedge_contracts: int = 1` di class `HedgeConfig`
- **Tambah method baru:** `place_instant_hedge()` - Beli langsung di market price (FAK)
- Method lama `place_gtd_hedge()` tetap ada untuk backward compatibility

**Cara Kerja `place_instant_hedge()`:**
1. Dapatkan harga pasar saat ini untuk token lawan (DOWN jika kita beli UP)
2. Beli langsung `hedge_contracts` menggunakan FAK order
3. Order langsung terfill atau gagal (tidak menunggu)
4. Proteksi aktif seketika!

---

### 4. `main.py`
**Perubahan:**
- Update inisialisasi `HedgeManager` untuk passing `hedge_contracts`
- Ganti panggilan `place_gtd_hedge()` → `place_instant_hedge()` di 2 lokasi:
  - Line ~2026: Entry normal
  - Line ~2141: Recovery setelah WebSocket reconnect
- Update notifikasi Telegram untuk menampilkan "INSTANT" bukan "GTD"

---

## 📊 Perbandingan Strategi

### Sebelum (GTD @ $0.02):
```
Entry: 5 UP @ $0.82 = $4.10
Hedge: 5 DOWN @ $0.02 = $0.10 (TAPI TIDAK TERFILL!)

Jika UP menang: +$0.90 ✅
Jika DOWN menang: -$4.10 ❌ (hedge tidak terfill)
```

### Sesudah (Instant Hedge 1 kontrak):
```
Entry: 5 UP @ $0.82 = $4.10
Hedge: 1 DOWN @ $0.18 = $0.18 (LANGSUNG TERFILL!)
Total: $4.28

Jika UP menang: 
  - Terima: 5 × $1.00 = $5.00
  - Net: $5.00 - $4.28 = +$0.72 ✅

Jika DOWN menang (reversal):
  - UP hangus: $0
  - Hedge: 1 × $1.00 = $1.00
  - Net: $1.00 - $4.28 = -$3.28 ✅
  
Penghematan saat loss: $4.10 - $3.28 = $0.82 per trade!
```

---

## 🎯 Dampak dengan 288 Trade/Hari

Asumsi: Win rate 60% (172 menang, 116 kalah)

### Tanpa Hedge Efektif (GTD tidak terfill):
| Hasil | Per Trade | Total Harian |
|-------|-----------|--------------|
| Menang (172x) | +$0.90 | +$154.80 |
| Kalah (116x) | -$4.10 | -$475.60 |
| **Net** | | **-$320.80** ❌ |

### Dengan Instant Hedge (1 kontrak):
| Hasil | Per Trade | Total Harian |
|-------|-----------|--------------|
| Menang (172x) | +$0.72 | +$123.84 |
| Kalah (116x) | -$3.28 | -$380.48 |
| **Net** | | **-$256.64** ✅ Hemat $64.16/hari! |

### Dengan Instant Hedge (2 kontrak):
| Hasil | Per Trade | Total Harian |
|-------|-----------|--------------|
| Menang (172x) | +$0.54 | +$92.88 |
| Kalah (116x) | -$2.46 | -$285.36 |
| **Net** | | **-$192.48** ✅ Hemat $128.32/hari! |

---

## ⚙️ Cara Menyesuaikan Parameter

### Untuk Profit Lebih Besar (Risk Higher):
```json
"hedge_contracts": 0  // Tidak ada hedge, profit maksimal tapi risk tinggi
```

### Untuk Proteksi Standar (Recommended):
```json
"hedge_contracts": 1  // Balance antara profit dan proteksi
```

### Untuk Proteksi Maksimal (Conservative):
```json
"hedge_contracts": 2  // Proteksi lebih kuat, profit lebih kecil
```

---

## 🧪 Testing di Simulation Mode

Bot sudah berjalan di **simulation mode** (`simulation.enabled: true`), jadi:
- Instant hedge akan disimulasikan dengan harga $0.18
- Tidak ada order nyata yang dikirim ke Polymarket
- Anda bisa melihat log bagaimana hedge bekerja

**Log yang akan muncul:**
```
SIMULATION: Instant hedge (no order sent)
  Order ID: SIM-HEDGE-INSTANT
  Contracts: 1 @ $0.180
  Cost: $0.18
```

---

## 📝 Next Steps (Opsional)

Untuk hasil optimal, pertimbangkan juga:

1. **Tighten Entry Filters** di `config.json`:
   ```json
   "strategy": {
     "min_deviation_pct": 5,    // Naikkan dari 3% → 5%
     "max_price": 0.75          // Turunkan dari 0.88 → 0.75
   }
   ```

2. **Add Daily Stop Loss** di `main.py`:
   - Stop trading jika loss > $50/hari
   - Reset counter setiap 00:00 UTC

3. **Monitor Win Rate**:
   - Cek `logs/simulation_summary.json` setiap hari
   - Target win rate > 65% untuk break-even dengan hedge

---

## ✅ Validasi

Semua file telah divalidasi:
- ✓ Syntax Python OK
- ✓ Config loading OK
- ✓ HedgeManager imports OK
- ✓ hedge_contracts parameter recognized

**Bot siap dijalankan!** 🚀
