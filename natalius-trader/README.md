# Natalius Trader

Open-source algorithmic trading platform inspired by NautilusTrader, dengan Rust-native core dan Python strategy API.

## Fitur Utama

- **Rust-native Core**: Performa tinggi dengan latensi nanodetik
- **Python Strategy API**: Mudah digunakan untuk mengembangkan strategi trading
- **Deterministic Backtesting**: Backtesting yang konsisten dan dapat direproduksi
- **Live Trading**: Deployment langsung ke berbagai exchange
- **Multi-Asset Support**: Crypto, Forex, Equities, Futures, Options
- **Event-Driven Architecture**: Arsitektur berbasis event untuk real-time processing

## Struktur Proyek

```
natalius-trader/
├── src/
│   ├── core/           # Engine utama, order management, risk management
│   ├── connectors/     # Koneksi ke exchange, websocket, database
│   ├── strategies/     # Implementasi strategi trading
│   ├── indicators/     # Indikator teknikal
│   ├── models/         # Model data (Trade, Signal, Order)
│   └── services/       # Layanan pendukung (notification, logger, backtester)
├── config/             # Konfigurasi untuk berbagai environment
├── tests/              # Unit tests dan integration tests
├── logs/               # Log file
├── data/               # Data historis dan cache
├── docs/               # Dokumentasi
└── scripts/            # Script utility
```

## Instalasi

```bash
# Clone repository
git clone https://github.com/yourusername/natalius-trader.git
cd natalius-trader

# Install dependencies
pip install -r requirements.txt

# Setup environment
cp .env.example .env
```

## Quick Start

```python
from natalius_trader import TradingEngine
from natalius_trader.strategies import MACDCrossover

# Initialize engine
engine = TradingEngine(config_path='config/default.yaml')

# Add strategy
strategy = MACDCrossover(
    symbol='BTC/USDT',
    fast_period=12,
    slow_period=26,
    signal_period=9
)

engine.add_strategy(strategy)

# Run backtest
results = engine.backtest(
    start_date='2024-01-01',
    end_date='2024-12-01'
)

print(results.summary())
```

## Exchange yang Didukung

- Binance
- Bybit
- OKX
- Coinbase
- Kraken
- BitMEX
- Deribit
- dYdX
- Hyperliquid
- Interactive Brokers

## Teknologi

- **Core**: Rust (untuk performa tinggi)
- **API**: Python 3.10+
- **Database**: PostgreSQL / Redis
- **Message Queue**: ZeroMQ / Redis PubSub
- **Web Framework**: FastAPI (untuk dashboard)

## Lisensi

MIT License

## Kontribusi

Kami menyambut kontribusi! Silakan baca [CONTRIBUTING.md](docs/CONTRIBUTING.md) untuk panduan detail.

## Disclaimer

Trading melibatkan risiko. Gunakan software ini dengan tanggung jawab Anda sendiri. Past performance tidak menjamin hasil masa depan.
