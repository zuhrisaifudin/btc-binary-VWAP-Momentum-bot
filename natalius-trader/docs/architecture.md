# Natalius Trader - Arsitektur & Struktur Proyek

## 📋 Ringkasan

**Natalius Trader** adalah platform algorithmic trading open-source yang terinspirasi oleh [NautilusTrader](https://nautilustrader.io/), dirancang untuk performa tinggi dengan arsitektur event-driven.

## 🏗️ Arsitektur Sistem

```
┌─────────────────────────────────────────────────────────────┐
│                    User Interface Layer                      │
│         (CLI Dashboard, Web UI, API Endpoints)              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Trading Engine Core                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Event Loop   │  │ Order Mgmt   │  │ Risk Mgmt    │      │
│  │   Manager    │  │   System     │  │   System     │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Strategy Layer                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │    MACD      │  │     RSI      │  │   Custom     │      │
│  │  Crossover   │  │  Scalping    │  │  Strategies  │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  Connector Layer                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ Binance  │ │  Bybit   │ │   OKX    │ │  Others  │       │
│  │ Adapter  │ │ Adapter  │ │ Adapter  │ │ Adapters │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 External Exchanges                           │
│         (Market Data & Order Execution APIs)                │
└─────────────────────────────────────────────────────────────┘
```

## 📁 Struktur Folder Detail

```
natalius-trader/
│
├── src/                          # Source code utama
│   ├── core/                     # Core engine components
│   │   ├── __init__.py           # Module exports
│   │   ├── engine.py             # Main trading engine (event loop)
│   │   ├── order_manager.py      # Order lifecycle management
│   │   ├── risk_manager.py       # Risk monitoring & limits
│   │   └── wallet.py             # Portfolio & position tracking
│   │
│   ├── connectors/               # Exchange adapters
│   │   ├── __init__.py
│   │   ├── exchange_api.py       # Base exchange connector
│   │   ├── websocket.py          # Real-time data streams
│   │   ├── binance_connector.py  # Binance-specific adapter
│   │   ├── bybit_connector.py    # Bybit-specific adapter
│   │   └── database.py           # Database connection pool
│   │
│   ├── strategies/               # Trading strategies
│   │   ├── __init__.py
│   │   ├── base_strategy.py      # Abstract base class
│   │   ├── macd_crossover.py     # MACD strategy implementation
│   │   ├── rsi_scalping.py       # RSI scalping strategy
│   │   └── natalius_custom.py    # Proprietary strategies
│   │
│   ├── indicators/               # Technical indicators
│   │   ├── __init__.py
│   │   ├── moving_average.py     # SMA, EMA, WMA
│   │   ├── macd.py               # MACD indicator
│   │   ├── rsi.py                # Relative Strength Index
│   │   └── bollinger_bands.py    # Bollinger Bands
│   │
│   ├── models/                   # Data models
│   │   ├── __init__.py
│   │   ├── trade.py              # Trade execution model
│   │   ├── signal.py             # Trading signal model
│   │   ├── order.py              # Order model
│   │   └── user.py               # User configuration model
│   │
│   └── services/                 # Supporting services
│       ├── __init__.py
│       ├── notification.py       # Telegram, Email alerts
│       ├── logger.py             # Logging configuration
│       ├── backtester.py         # Backtesting engine
│       └── metrics.py            # Performance metrics
│
├── config/                       # Configuration files
│   ├── default.yaml              # Default configuration
│   ├── production.yaml           # Production settings
│   ├── backtest.yaml             # Backtest-specific settings
│   └── exchanges.yaml            # Exchange configurations
│
├── tests/                        # Test suite
│   ├── unit/                     # Unit tests
│   ├── integration/              # Integration tests
│   └── fixtures/                 # Test data fixtures
│
├── logs/                         # Application logs
│   ├── natalius.log              # Main log file
│   └── trades.log                # Trade execution log
│
├── data/                         # Data storage
│   └── historical_prices/        # Historical market data
│       ├── binance/
│       ├── bybit/
│       └── okx/
│
├── docs/                         # Documentation
│   ├── architecture.md           # Architecture documentation
│   ├── api_reference.md          # API documentation
│   ├── strategies.md             # Strategy guide
│   └── deployment.md             # Deployment guide
│
├── scripts/                      # Utility scripts
│   ├── download_data.py          # Download historical data
│   ├── run_backtest.py           # Run backtest CLI
│   └── deploy.sh                 # Deployment script
│
├── .env.example                  # Environment variables template
├── .gitignore                    # Git ignore rules
├── requirements.txt              # Python dependencies
├── README.md                     # Project overview
└── docker-compose.yml            # Docker setup (optional)
```

## 🔧 Komponen Utama

### 1. **Trading Engine** (`src/core/engine.py`)
- Event-driven architecture
- Multi-strategy support
- Real-time market data processing
- Order execution coordination

### 2. **Strategy Framework** (`src/strategies/`)
- Base class untuk semua strategi
- Signal generation interface
- Lifecycle management (on_start, on_stop, on_fill, on_cancel)

### 3. **Exchange Connectors** (`src/connectors/`)
- Unified API untuk multiple exchanges
- WebSocket streaming untuk real-time data
- REST API untuk order execution

### 4. **Risk Management** (`src/core/risk_manager.py`)
- Position size limits
- Drawdown monitoring
- Daily loss limits
- Stop-loss enforcement

### 5. **Backtesting Engine** (`src/services/backtester.py`)
- Deterministic replay
- Commission & slippage modeling
- Performance metrics calculation

## 🚀 Fitur Utama

| Fitur | Deskripsi |
|-------|-----------|
| **Multi-Exchange** | Support Binance, Bybit, OKX, Coinbase, Kraken, dll |
| **Multi-Asset** | Crypto, Forex, Equities, Futures, Options |
| **Low Latency** | Optimized untuk eksekusi cepat (nanosecond timestamps) |
| **Deterministic Backtesting** | Hasil backtest konsisten dan reproducible |
| **Python API** | Mudah digunakan untuk develop strategi custom |
| **Risk Management** | Built-in risk controls dan monitoring |
| **Real-time Monitoring** | Dashboard dan alert via Telegram/Email |

## 📝 Contoh Penggunaan

```python
from natalius_trader import TradingEngine
from natalius_trader.strategies import MACDCrossover

# Initialize engine dengan config
engine = TradingEngine(config_path='config/default.yaml')

# Buat dan tambahkan strategy
strategy = MACDCrossover(
    symbol='BTC/USDT',
    fast_period=12,
    slow_period=26,
    signal_period=9,
    config={'quantity': 0.001}
)

engine.add_strategy(strategy)

# Jalankan backtest
results = engine.backtest(
    start_date='2024-01-01',
    end_date='2024-12-01'
)

# Print hasil
print(f"Total Return: {results['total_return']:.2%}")
print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
print(f"Max Drawdown: {results['max_drawdown']:.2%}")
print(f"Win Rate: {results['win_rate']:.2%}")
```

## 🛠️ Teknologi Stack

- **Core Language**: Python 3.10+ (dengan opsi Rust untuk performance-critical components)
- **Async Runtime**: asyncio + uvloop
- **Data Processing**: NumPy, Pandas
- **Technical Analysis**: TA-Lib, pandas-ta
- **Database**: PostgreSQL + Redis
- **Message Queue**: ZeroMQ
- **Logging**: Loguru
- **Testing**: pytest, pytest-asyncio

## 📄 Lisensi

MIT License - Lihat file LICENSE untuk detail.

## ⚠️ Disclaimer

Trading cryptocurrency dan instrumen finansial lainnya melibatkan risiko tinggi. 
Gunakan software ini dengan tanggung jawab Anda sendiri. 
Past performance tidak menjamin hasil masa depan.
