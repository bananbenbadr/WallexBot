# Changelog

All notable changes to this project will be documented in this file.

This project aims to follow Keep a Changelog and Semantic Versioning (MAJOR.MINOR.PATCH) conventions.

## [Unreleased]
- Potential: add metrics/health endpoints, improve WebSocket subscription robustness for different providers, expand strategy hooks, and add unit tests for polling parser.

## [0.1.2] - 2025-08-23
### Fixed
- Resolved Pyright type error in WebSocket client by replacing decorator-based registration with an explicit handler for the `"Broadcaster"` channel.
- Cleaned up duplicated/invalid code paths in `src/wallex/ws_client.py` and ensured explicit callback registration via `self.sio.on("Broadcaster", _on_message)`.

### Changed
- Added explicit info log in polling loop: `Polling fetched <N> new trades` to make REST fallback activity visible in logs.

## [0.1.1] - 2025-08-23
### Added
- Safety flag: `DRY_RUN` to gate order placement (logs and skips actual order creation when enabled).
- Reliability flags to support REST polling fallback when WebSocket is idle or disconnected:
  - `ENABLE_POLLING`
  - `POLLING_INTERVAL_SEC`
  - `WS_IDLE_TIMEOUT_SEC`
- REST polling loop in `src/main.py` that:
  - Activates when WS is disconnected or idle beyond `WS_IDLE_TIMEOUT_SEC`.
  - Fetches recent trades from HTTP and deduplicates via last seen timestamp.
  - Feeds trades through a unified `handle_trade` path shared with WebSocket events.

### Changed
- Centralized trade handling into a `handle_trade` helper for consistent processing from both WS and HTTP polling.
- Added detailed logs around order decisions, DRY_RUN gating, and polling activity.

## [0.1.0] - 2025-08-23
### Added
- Initial public release of the Wallex trading bot:
  - HTTP client with endpoints for markets, trades, order book depth, open orders, place order, and cancel order.
  - WebSocket client using `python-socketio` with auto-reconnect and subscription management.
  - Optional LLM analysis using Google Gemini; gracefully falls back to a safe decision if LLM fails.
  - Trading engine that converts quote amount to market order quantity, applies minimal quantity checks, and logs decisions.
  - E2E script exercising HTTP endpoints, WebSocket ingestion, LLM analysis, and engine decision flow.
  - Config system with `.env` support and sane defaults (symbol, amounts, logging level, etc.).

---

Guidelines:
- Keep entries concise, grouped by Added/Changed/Fixed/Removed/Deprecated/Security where applicable.
- Document user-facing changes, config flags, new commands, and behavior changes.
- Update the date in ISO format (YYYY-MM-DD).