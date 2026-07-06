# Proyeksi Saldo Mingguan Bot Trading Polymarket (Modal Awal $20)

Dokumen ini memberikan simulasi proyeksi saldo mingguan untuk bot trading BTC 5-Menit menggunakan strategi **"Dual-Side Scaling & Regime Adaptation"** berbasis **Half-Kelly Criterion**.

## Detail Parameter Simulasi
*   **Modal Awal:** `$20.00`
*   **Frekuensi Perdagangan:** 288 trade per hari (siklus 5 menit penuh selama 24 jam)
*   **Rasio Alokasi Sizer:** Dominan $75\%$ (`$15.00`), Asuransi $25\%$ (`$5.00`)
*   **Batas Maksimal Kontrak:** 50 kontrak per trade (untuk mencerminkan batas nyata likuiditas Polymarket & menghindari slippage besar)
*   **Win Probability Average:** Rata-rata peluang menang berkisar di angka $65\% - 85\%$ (berdasarkan tabel win rate historis).

---

## Proyeksi Pertumbuhan Saldo Harian (7 Hari)

Berikut adalah estimasi pertumbuhan saldo Anda dari Hari 1 hingga Hari 7 berdasarkan simulasi compounding yang aman:

| Hari | Estimasi Saldo Akhir | Jumlah Trade Terekesekusi | Estimasi PnL Bersih Harian | Status Akumulasi |
| :--- | :--- | :--- | :--- | :--- |
| **Hari 0** | `$20.00` | - | - | Modal Awal |
| **Hari 1** | **`$967.05`** | 222 trade | `+$947.05` | Compounding Cepat |
| **Hari 2** | **`$2,127.65`** | 220 trade | `+$1,160.60` | Mulai Terbatasi Cap 50 Kontrak |
| **Hari 3** | **`$3,354.71`** | 244 trade | `+$1,227.06` | Pertumbuhan Stabil |
| **Hari 4** | **`$4,184.09`** | 218 trade | `+$829.38` | Pertumbuhan Stabil |
| **Hari 5** | **`$4,925.55`** | 226 trade | `+$741.46` | Pertumbuhan Stabil |
| **Hari 6** | **`$5,837.25`** | 208 trade | `+$911.70` | Pertumbuhan Stabil |
| **Hari 7** | **`$6,214.16`** | 216 trade | `+$376.91` | **Total Akumulasi Mingguan** |

*Catatan: Sisa trade dari total 288 per hari dilewati secara otomatis oleh sistem karena kondisi pasar terdeteksi tidak menguntungkan (Expected Value < 0) atau spread bid-ask terlalu lebar.*

---

## Catatan Risiko Penting (Disclaimer)
1.  **Likuiditas Pasar:** Hasil di atas mengasumsikan order limit Anda selalu terisi penuh di pasar (maker). Pada kenyataannya, kecepatan antrean order book dan ketersediaan lawan transaksi dapat mengurangi persentase eksekusi riil.
2.  **Volatilitas Win Rate:** Kinerja historis win rate 65%-85% tidak menjamin kinerja masa depan. Jika pasar mengalami tren anomali panjang, bot dilindungi oleh fitur **Circuit Breaker (cooldown 60 menit setelah 5x loss beruntun)** untuk membatasi risiko kerugian berlebih.
