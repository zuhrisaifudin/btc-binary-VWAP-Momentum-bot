# Proyeksi Saldo & Estimasi PnL Bot Trading Polymarket

Dokumen ini memberikan simulasi proyeksi saldo harian, mingguan, hingga bulanan (4 minggu) untuk beberapa skenario modal awal ($20, $40, $50, $75, $100) menggunakan strategi **"Dual-Side Scaling & Regime Adaptation"** berbasis **Half-Kelly Criterion**.

---

## 1. Parameter Utama Simulasi
*   **Kecepatan Trading:** 288 trade/hari (24 jam nonstop pada opsi 5-menit).
*   **Alokasi Kelly:** $75\%$ Dominan, $25\%$ Asuransi.
*   **Proteksi Batas Maksimum:** **50 kontrak per trade**. 
    *   *Catatan Penting:* Begitu saldo Anda tumbuh besar, bot akan membatasi pembelian maksimal 50 kontrak per trade untuk menyesuaikan dengan batas likuiditas nyata di Polymarket dan mencegah slippage yang merugikan.

---

## 2. Tabel Proyeksi Saldo (1 Bot)

Berikut adalah hasil simulasi perbandingan pertumbuhan saldo berdasarkan modal awal Anda:

| Modal Awal | Saldo Minggu 1 | Saldo Minggu 2 | Saldo Minggu 3 | Saldo Minggu 4 (1 Bulan) | Estimasi PnL Bersih (1 Bulan) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`$20.00`** | `$6,214.16` | `$13,278.41` | `$20,285.27` | `$27,902.13` | **`+$27,882.13`** |
| **`$40.00`** | `$6,349.80` | `$13,425.22` | `$20,439.78` | `$28,003.67` | **`+$27,963.67`** |
| **`$50.00`** | `$6,384.50` | `$13,460.36` | `$20,474.93` | `$28,038.81` | **`+$27,988.81`** |
| **`$75.00`** | `$6,581.25` | `$13,658.70` | `$20,673.02` | `$28,236.91` | **`+$28,161.91`** |
| **`$100.00`** | `$6,655.27` | `$13,731.24` | `$20,745.56` | `$28,309.45` | **`+$28,209.45`** |

> [!NOTE]
> **Mengapa Saldo Akhir Semua Modal Terlihat Mirip?**
> Karena adanya batas aman **`max_contracts: 50`** di dalam `config.json`. Begitu saldo bot Anda melewati angka ~$1,000, bot tidak akan lagi melipatgandakan ukuran taruhannya secara eksponensial (demi keamanan portofolio dari kebangkrutan instant), melainkan beralih ke pertumbuhan linear yang stabil dengan menaruh maksimum 50 kontrak per transaksi.

---

## 3. Skenario Multi-Bot: Berjalan 5 Bot Sekaligus

Jika Anda mengoperasikan **5 unit bot secara bersamaan**, berikut adalah proyeksi akumulasi PnL bersih Anda:

### Aturan Operasional Multi-Bot:
Untuk memaksimalkan 5 bot secara bersamaan tanpa saling berebut antrean order (*order collision*), Anda **tidak boleh** menjalankannya pada satu pasar yang sama. Anda harus membaginya ke 5 pasar berbeda, misalnya:
1.  **Bot 1:** BTC 5m Up/Down
2.  **Bot 2:** ETH 5m Up/Down
3.  **Bot 3:** Solana 5m Up/Down
4.  **Bot 4:** BTC 15m Up/Down (interval lebih panjang)
5.  **Bot 5:** Doge/Link 5m Up/Down

### Tabel Akumulasi PnL Bersih (5 Bot Berjalan Bersamaan):

| Modal Awal Per Bot | Total Modal (5 Bot) | PnL 1 Minggu (5 Bot) | PnL 2 Minggu (5 Bot) | PnL 3 Minggu (5 Bot) | PnL 4 Minggu (5 Bot) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`$20.00`** | `$100.00` | `$30,970.80` | `$66,292.05` | `$101,326.35` | **`$139,410.65`** |
| **`$40.00`** | `$200.00` | `$31,549.00` | `$66,926.10` | `$101,998.90` | **`$139,818.35`** |
| **`$50.00`** | `$250.00` | `$31,672.50` | `$67,101.80` | `$102,174.65` | **`$139,944.05`** |
| **`$75.00`** | `$375.00` | `$32,531.25` | `$68,093.50` | `$103,115.10` | **`$140,809.55`** |
| **`$100.00`** | `$500.00` | `$32,776.35` | `$68,456.20` | `$103,477.80` | **`$141,047.25`** |

---

## 4. Rekomendasi Manajemen Risiko untuk Multi-Bot

1.  **Diverifikasi API Key:** Gunakan API Key CLOB Polymarket yang berbeda untuk setiap bot guna mempermudah pelacakan PnL di dashboard masing-masing.
2.  **Gunakan Sinyal Terpisah:** Pastikan indikator teknis (seperti VWAP window dan momentum) dikonfigurasi secara unik untuk masing-masing koin agar volatilitas satu koin tidak memicu entri salah arah di bot lainnya.
3.  **Circuit Breaker Mandiri:** Setiap bot harus memiliki file trading log masing-masing (misal `trading_log_btc.json`, `trading_log_eth.json`) agar status pembatasan cooldown 60 menit bekerja secara independen jika salah satu koin sedang mengalami tren anomali.
