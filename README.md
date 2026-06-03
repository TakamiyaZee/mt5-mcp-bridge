# MT5 MCP Bridge

**MetaTrader 5 + MCP (Model Context Protocol)** — Expose MT5 trading capabilities as MCP tools for LLM agents.

## Architecture

```
LLM Agent
  └── MCP Client (stdio)
       └── server.py  (FastMCP, Python)
            └── mt5linux library
                 └── RPyC client → localhost:8001
                      └── Wine Python 3.11
                           ├── MetaTrader5 SDK
                           └── MetaTrader 5 terminal
```

Two-tier design:
1. **Bridge** — Wine Python + MT5 terminal, exposes RPyC service on port 8001
2. **MCP Server** — Linux `python3` runs FastMCP, connects to bridge via `mt5linux`

## Features

### Read-Only Tools
| Tool | Description |
|------|-------------|
| `get_account_info` | Balance, equity, profit, margin, leverage |
| `get_symbol_price` | Latest bid/ask price |
| `get_symbol_info` | Full spec (digits, spread, lot size limits) |
| `get_symbols` / `get_all_symbols` | List available symbols |
| `get_candles_latest` | Last N OHLCV candles (M1–MN1) |
| `get_candles_by_date` | Candles by date range |
| `get_all_positions` | Open positions |
| `get_all_pending_orders` | Pending orders |

### Trading Tools
| Tool | Description |
|------|-------------|
| `open_position` | Market BUY/SELL with SL/TP |
| `close_position` | Close by ticket ID |
| `close_all_positions` | Close all positions |
| `modify_position` | Change SL/TP on open position |
| `place_pending_order` | BUY_LIMIT/SELL_LIMIT/BUY_STOP/SELL_STOP |
| `cancel_pending_order` | Cancel by ticket |

### Quantitative Analysis Tools
| Tool | Description |
|------|-------------|
| `calculate_kelly_position` | Position sizing via Kelly criterion |
| `validate_trade_signal` | Pre-trade checks (spread, stops, volatility) |
| `get_technical_indicators` | RSI, MACD, Bollinger Bands, SMA, ATR |
| `calculate_symbol_correlation` | Correlation matrix |
| `check_news_blackout` | Economic calendar blackout check |
| `get_portfolio_risk_snapshot` | Portfolio VaR, exposure, daily P&L |
| `get_market_regime` | Trend/range detection via ADX & BB width |

### Economic Calendar Tools
| Tool | Description |
|------|-------------|
| `get_economic_calendar_today` | Today's events (NY time) |
| `get_economic_calendar_yesterday` | Yesterday's events |
| `get_economic_calendar_date` | Specific date events |

## Setup

### Prerequisites
```bash
# System deps
sudo apt-get install xvfb winbind

# Python deps (Linux host)
pip install mt5linux rpyc "mcp[cli]"
```

### Wine + Python 3.11
```bash
# Install Python 3.11 in MT5 Wine prefix
WINEPREFIX=$HOME/.mt5 wine python-3.11.9-amd64.exe /quiet \
  InstallAllUsers=0 PrependPath=1 Include_test=0 TargetDir=C:\\Python311

# VC++ Redist for NumPy
WINEPREFIX=$HOME/.mt5 wine vc_redist.x64.exe /install /quiet /norestart

# Install packages
WINEPREFIX=$HOME/.mt5 wine "C:\\Python311\\python.exe" -m pip install \
  "numpy==1.23.5" MetaTrader5 mt5linux rpyc
```

### Credentials
Set via environment variables (never hardcode):
```bash
export MT5_LOGIN=12345678
export MT5_PASSWORD=your_password
export MT5_SERVER=YourBroker-Server
export EARNINGS_API_KEY=your_earnings_api_key  # optional
```

## Running

### 1. Start Bridge
```bash
MT5_LOGIN=12345678 MT5_PASSWORD=pass MT5_SERVER=Broker-Server \
  bash start-mt5-bridge.sh
```
Verify: `ss -tlnp | grep 8001`

### 2. Start MCP Server (standalone)
```bash
python3 server.py
```

### 3. Register with Hermes (optional)
```yaml
# ~/.hermes/config.yaml
mcp_servers:
  metatrader:
    command: python3
    args: [/path/to/server.py]
    enabled: true
    timeout: 180
    connect_timeout: 30
```

## Hedge Fund Quant System

Multi-agent trading pipeline at `run_trading_cycle.py`:

```
Cron Tick → [MarketIntel | EconCalendar | TechAnalysis]
          → RiskManager → PortfolioManager → Execution
```

### Agent Workflow (agents/ directory)
- `01_market_intel.md` — Geopolitical & macro risk analysis
- `02_econ_calendar.md` — Economic data parser
- `03_tech_analysis.md` — Quant TA signal generator
- `04_risk_manager.md` — Position sizing & filters
- `05_portfolio_manager.md` — Capital allocation

### Risk Parameters
- Max 1% risk/trade, 5% symbol exposure, 3% daily loss
- Min RR 1.5:1, Kelly fraction 0.25
- Correlation filter: max 2 same-direction correlated pairs
- 15-minute news blackout pre/post high-impact events

### Run
```bash
# Dry run
python3 run_trading_cycle.py --dry-run

# Status check
python3 run_trading_cycle.py --status

# Live
python3 run_trading_cycle.py
```

## Security
- **Never commit credentials** — use `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` env vars
- See `.env.example` for required variables
- Bridge binds to `localhost:8001` (not exposed to network)
- MCP runs on stdio by default (not network-accessible)

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Bridge port 8001 not listening | Bridge process died | Restart `start-mt5-bridge.sh` |
| `IPC timeout` on init | MT5 terminal not ready under Wine | Open MT5 once manually to clear dialogs |
| Retcode 10027 | AutoTrading disabled | Enable in MT5: Tools → Options → Expert Advisors |
| Retcode 10030 | Unsupported fill mode | Use `ORDER_FILLING_FOK` for HF Markets |
| `Invalid stops` (10016) | Wrong SL/TL direction | BUY: SL < entry < TP; SELL: TP < entry < SL |

## License
MIT
