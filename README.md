# MT5 MCP Bridge

<div align="center">

**MetaTrader 5 + MCP (Model Context Protocol)**

Expose MT5 trading capabilities as MCP tools for AI agents.

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-brightgreen)]()
[![MCP](https://img.shields.io/badge/MCP-FastMCP-orange)]()

</div>

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

---

## Features

### Read-Only Tools (10)
| Tool | Description |
|------|-------------|
| `get_account_info` | Balance, equity, profit, margin, leverage |
| `get_symbol_price` | Latest bid/ask price |
| `get_symbol_info` | Full spec (digits, spread, lot size limits) |
| `get_symbols` / `get_all_symbols` | List symbols by group |
| `get_candles_latest` | Last N OHLCV candles (M1–MN1) |
| `get_candles_by_date` | Candles by date range |
| `get_all_positions` | Open positions as CSV |
| `get_all_pending_orders` | Pending orders as CSV |

### Trading Tools (8)
| Tool | Description |
|------|-------------|
| `open_position` | Market BUY/SELL with SL/TP |
| `close_position` | Close by ticket ID |
| `close_all_positions` | Close all positions |
| `modify_position` | Change SL/TP on open position |
| `place_pending_order` | BUY_LIMIT/SELL_LIMIT/BUY_STOP/SELL_STOP |
| `cancel_pending_order` | Cancel by ticket |
| `cancel_all_pending_orders` | Cancel all pending |

### Quantitative Analysis Tools (7)
| Tool | Description |
|------|-------------|
| `calculate_kelly_position` | Position sizing via Kelly criterion |
| `validate_trade_signal` | Pre-trade checks (spread, stops, volatility) |
| `get_technical_indicators` | RSI, MACD, Bollinger, SMA, ATR |
| `calculate_symbol_correlation` | Correlation matrix |
| `check_news_blackout` | Economic calendar blackout check |
| `get_portfolio_risk_snapshot` | VaR, exposure, daily P&L, breaches |
| `get_market_regime` | Trend/range detection |

### Economic Calendar Tools (3)
| Tool | Description |
|------|-------------|
| `get_economic_calendar_today` | Today's events (NY time) |
| `get_economic_calendar_yesterday` | Yesterday's events |
| `get_economic_calendar_date` | Specific date |

**Total: 28 MCP tools**

---

## Quick Start

### Prerequisites
```bash
sudo apt-get install xvfb winbind
pip install mt5linux rpyc "mcp[cli]"
```

### Wine Python + MT5
```bash
WINEPREFIX=$HOME/.mt5 wine python-3.11.9-amd64.exe /quiet \
  InstallAllUsers=0 PrependPath=1 Include_test=0 TargetDir=C:\\Python311

WINEPREFIX=$HOME/.mt5 wine "C:\\Python311\\python.exe" -m pip install \
  "numpy==1.23.5" MetaTrader5 mt5linux rpyc
```

### Set Credentials (always via env, never hardcode)
```bash
export MT5_LOGIN=12345678
export MT5_PASSWORD=your_p...n
export MT5_SERVER=YourBroker-Server
```

### Start Bridge
```bash
bash start-mt5-bridge.sh
# Verify → ss -tlnp | grep 8001
```

### Run MCP Server
```bash
python3 server.py
```

---

## MCP Client Integration

### Claude Desktop
```json
{
  "mcpServers": {
    "metatrader": {
      "command": "python3",
      "args": ["/path/to/mt5-mcp-bridge/server.py"],
      "env": {
        "MT5_BRIDGE_HOST": "localhost",
        "MT5_BRIDGE_PORT": "8001"
      }
    }
  }
}
```

### Hermes Agent
```yaml
# ~/.hermes/config.yaml
mcp_servers:
  metatrader:
    command: python3
    args: [/path/to/mt5-mcp-bridge/server.py]
    enabled: true
    timeout: 180
    connect_timeout: 30
```

Then in Hermes session: `/reload-mcp` → `hermes mcp test metatrader`

### Standards-Based MCP Client
Any MCP client that supports **stdio transport** can use this server directly:
```bash
python3 /path/to/mt5-mcp-bridge/server.py
```

---

## Hedge Fund Quant System

Multi-agent trading pipeline in `run_trading_cycle.py`:

```
Tick → [MarketIntel | EconCalendar | TechAnalysis]
     → RiskManager → PortfolioManager → Execution
```

### Agent Prompts (`agents/`)
| File | Role |
|------|------|
| `01_market_intel.md` | Geopolitical & macro risk analysis |
| `02_econ_calendar.md` | Economic calendar parser (NFP, CPI, Fed) |
| `03_tech_analysis.md` | Quant TA signals (RSI, MACD, patterns) |
| `04_risk_manager.md` | Position sizing, filters, correlation |
| `05_portfolio_manager.md` | Capital allocation, hedging |

### Risk Parameters
| Parameter | Value |
|-----------|-------|
| Max risk per trade | 1% |
| Max symbol exposure | 5% |
| Max daily loss | 3% |
| Min risk-reward | 1.5:1 |
| Kelly fraction | 0.25 (conservative) |
| Correlation limit | 0.70 |
| News blackout | ±15 min high-impact events |

### Run the Cycle
```bash
# Dry run (no execution)
python3 run_trading_cycle.py --dry-run

# Status check
python3 run_trading_cycle.py --status

# Live
python3 run_trading_cycle.py
```

---

## Security

### What's Protected
| Risk | Mitigation |
|------|-----------|
| Credential leak | `MT5_LOGIN`/`PASSWORD`/`SERVER` via env only, never in code |
| Network exposure | Bridge binds to `localhost:8001`, MCP uses stdio |
| API key leak | `EARNINGS_API_KEY` via env only, no fallback default |
| .env file | Listed in `.gitignore` — never committed |

### Before Committing
```bash
# Scan for secrets
git diff --cached | grep -E '(password|secret|api_key|token)' || echo "clean"
```

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
# Then fill in your credentials
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Port 8001 not listening | Bridge died | Restart `start-mt5-bridge.sh` |
| `IPC timeout` (-10005) | Terminal not ready | Open MT5 manually once to clear dialogs |
| Retcode `10027` | AutoTrading disabled | Enable in common.ini: `[Experts] Enabled=1` |
| Retcode `10030` | Unsupported fill | Use `ORDER_FILLING_FOK` for HF Markets |
| Retcode `10016` | Wrong SL direction | BUY: SL<entry<TP; SELL: TP<entry<SL |
| `metatrader (stdio) — failed` | MCP process stale | `kill $(pgrep -f server.py)` — Hermes respawns |
| MCP shows 0 tools | Bridge unreachable | Check `ss -tlnp | grep 8001` first |

---

## Development

```bash
# Clone
git clone https://github.com/TakamiyaZee/mt5-mcp-bridge.git
cd mt5-mcp-bridge

# Test connection (requires running bridge)
python3 test_stdio.py

# Add new tool
Just add `@mcp.tool()` function in `server.py`
```

---

## License

[MIT](LICENSE) — use freely, no warranty.
