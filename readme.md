# Wallex Trading Bot (Python)

A modular trading bot for the Wallex exchange featuring:
- HTTP and WebSocket market data ingestion
- Optional LLM-based signal generation (Google Gemini)
- A simple, safe trading engine
- REST polling fallback when WebSocket is idle or unavailable
- DRY_RUN safety switch to prevent unintended live orders

> This repository is intended for educational purposes. Trading involves risk. Use DRY_RUN and validate thoroughly before placing real orders.

## Features
- Robust REST client: markets, trades, order book depth, open orders, place/cancel orders.
- WebSocket client with auto-reconnect and subscription management.
- Unified trade processing path from either WS stream or REST polling fallback.
- LLM integration (Gemini) that returns structured decisions; errors degrade to safe "flat".
- TradingEngine converts quote budget to market order quantity and applies basic safety checks.
- Configurable via environment variables with `.env` support.
- E2E script to smoke-test HTTP endpoints, basic WS ingestion, LLM, and trading engine flows.

## Project Structure
```
├── src/
│   ├── config.py                 # Settings + .env loader
│   ├── main.py                   # Bot entrypoint; WS + polling fallback + decision loop
│   ├── engine/trading_engine.py  # Order sizing and decision handling
│   ├── llm/gemini_client.py      # LLM client and prompt/response parsing
│   ├── models/types.py           # Data classes for LLM and orders
│   ├── utils/logging.py          # Logging setup
│   └── wallex/
│       ├── api_client.py         # HTTP client for Wallex endpoints
│       └── ws_client.py          # WebSocket client (python-socketio)
└── tests/
    └── e2e_test.py               # End-to-end validation script
```

## Requirements
- Python 3.10+
- A Wallex API key (only required for authenticated endpoints like placing orders)
- Optional: a Google Gemini API key for LLM analysis

## Installation (Windows/PowerShell)
```powershell
# From the repository root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Optional developer tooling
pip install pyright pytest
```

## Configuration
Copy `.env.example` to `.env` and adjust as needed. The app reads these variables with sane defaults:

- WALLEX_API_KEY: API key for authenticated calls (default: empty)
- WALLEX_BASE_URL: Base REST/WS URL (default: https://api.wallex.ir)
- TRADE_SYMBOL: Trading symbol, e.g. BTCUSDT (default: BTCUSDT)
- USE_LLM: Enable LLM analysis (default: true)
- ENABLE_PINE: Placeholder flag for strategy module toggling (default: true)
- GEMINI_API_KEY: Google Gemini API key (default: empty)
- GEMINI_MODEL: Gemini model name (default: gemini-1.5-flash)
- TRADE_AMOUNT_USDT: Quote amount to spend per trade (default: 10)
- LOG_LEVEL: Logging level (default: INFO)
- DRY_RUN: If true, log decisions but do not place real orders (default: true)
- ENABLE_POLLING: Enable REST polling fallback for trades (default: true)
- POLLING_INTERVAL_SEC: Polling interval in seconds (default: 5)
- WS_IDLE_TIMEOUT_SEC: Consider WS idle after N seconds (default: 15)

Example `.env`:
```env
WALLEX_API_KEY=
WALLEX_BASE_URL=https://api.wallex.ir
TRADE_SYMBOL=BTCUSDT
USE_LLM=true
ENABLE_PINE=true
GEMINI_API_KEY=
GEMINI_MODEL=gemini-1.5-flash
TRADE_AMOUNT_USDT=10
LOG_LEVEL=INFO
DRY_RUN=true
ENABLE_POLLING=true
POLLING_INTERVAL_SEC=5
WS_IDLE_TIMEOUT_SEC=15
```

## Usage
Activate your virtual environment and start the bot:
```powershell
.\.venv\Scripts\Activate.ps1
# Option A
python -m src.main
# Option B (equivalent)
python -c "import src.main as m; m.run()"
```

Expected behavior:
- The bot connects to WebSocket and subscribes to `<TRADE_SYMBOL>@trade`.
- If WS is idle/disconnected for longer than `WS_IDLE_TIMEOUT_SEC`, it polls recent trades via REST.
- Trades from both sources flow through the same processing path.
- Every few trades, the bot queries the LLM (when enabled) and the engine decides whether to submit an order.
- When `DRY_RUN=true`, orders are logged and skipped.

### Running the E2E script
```powershell
.\.venv\Scripts\Activate.ps1
python .\tests\e2e_test.py
```
The script:
- Calls HTTP endpoints (markets, trades, depth, open orders)
- Exercises WebSocket ingestion
- Runs a synthetic LLM+Engine decision flow
- Exits with non-zero status if core checks fail

## Troubleshooting
- WebSocket connection errors: ensure `python-socketio` and `websocket-client` are installed (`pip install -r requirements.txt`). Check proxies/firewalls.
- No trades arriving: ensure your symbol is valid and liquid. Polling should log `Polling fetched <N> new trades` when active.
- Type checking: run `pyright` from your venv (`.\.venv\Scripts\pyright`).
- API failures: confirm `WALLEX_BASE_URL` and network connectivity.

## Contributing
- Open an issue to discuss substantial changes.
- Fork the repo and create a feature branch.
- Keep changes focused and add tests when possible.
- Run formatting, type checking, and E2E before submitting:
  ```powershell
  .\.venv\Scripts\Activate.ps1
  pyright
  python .\tests\e2e_test.py
  ```
- Submit a PR with a clear description. Update `changelog.md` under an `[Unreleased]` section following the existing style.

## Security & Safety
- Keep `DRY_RUN=true` while developing and validating.
- Never commit secrets. Use `.env` locally and environment variables in CI/CD.

## Changelog
See [changelog.md](./changelog.md) for release notes.