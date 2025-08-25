import time
import os
import threading
from src.config import load_settings
from src.utils.logging import setup_logging, get_logger
from src.wallex.api_client import WallexAPIClient
from src.wallex.ws_client import WallexWSClient
from src.llm.gemini_client import GeminiClient, LLMInput
from src.engine.trading_engine import TradingEngine


logger = get_logger(__name__)


def run():
    settings = load_settings()
    setup_logging(settings.log_level)

    wallex_http = WallexAPIClient(api_key=settings.wallex_api_key, base_url=settings.wallex_base_url)
    ws = WallexWSClient(base_url=settings.wallex_base_url)

    llm = None
    if settings.use_llm and settings.gemini_api_key:
        llm = GeminiClient(api_key=settings.gemini_api_key, model=settings.gemini_model)

    engine = TradingEngine(symbol=settings.symbol, quote_amount=settings.trade_amount_quote)

    # State for trade processing and idle detection
    recent_trades = []
    last_trade_ts = 0
    last_activity = time.time()
    stop_event = threading.Event()

    def handle_trade(data: dict):
        nonlocal recent_trades, last_trade_ts, last_activity
        if not isinstance(data, dict):
            return
        # Extract timestamp and price fields defensively
        try:
            ts = int(data.get("ts") or data.get("T") or data.get("t") or 0)
        except Exception:
            ts = 0
        price_val = data.get("price") or data.get("p")
        try:
            price = float(price_val) if price_val is not None else 0.0
        except Exception:
            price = 0.0

        # Deduplicate by timestamp when available
        if ts and ts <= last_trade_ts:
            return
        if ts:
            last_trade_ts = ts
        last_activity = time.time()

        recent_trades.append(data)
        if len(recent_trades) > 200:
            recent_trades = recent_trades[-200:]

        if len(recent_trades) % 5 == 0:
            logger.info(f"Trades received: {len(recent_trades)}; last price: {price_val}")

        # Every N trades, make a decision
        if llm and len(recent_trades) % 6 == 0 and price > 0:
            decision = llm.analyze(LLMInput(symbol=settings.symbol, timeframe="live", recent_trades=recent_trades[-20:]))
            order_req = engine.decide_order(price, decision)
            if order_req:
                if settings.dry_run:
                    logger.info("DRY_RUN enabled; skipping order placement.")
                elif not settings.wallex_api_key:
                    logger.warning("WALLEX_API_KEY not set; skipping order placement.")
                else:
                    try:
                        resp = wallex_http.place_order(order_req)
                        logger.info(f"Order placed: {resp}")
                    except Exception as e:
                        logger.exception(f"Order placement failed: {e}")

    def on_msg(channel: str, data: dict):
        if channel.endswith("@trade"):
            handle_trade(data)

    ws.on_message(on_msg)

    # Polling fallback thread to feed trades when WS is idle/disconnected
    def polling_loop():
        nonlocal last_activity, last_trade_ts
        if settings.enable_polling:
            logger.info(
                f"Polling fallback enabled: interval={settings.polling_interval_sec}s, idle_timeout={settings.ws_idle_timeout_sec}s"
            )
        while not stop_event.is_set():
            try:
                if not settings.enable_polling:
                    time.sleep(1)
                    continue
                ws_connected = getattr(ws.sio, "connected", False)
                idle = (time.time() - last_activity) > settings.ws_idle_timeout_sec
                should_poll = (not ws_connected) or idle
                if not should_poll:
                    time.sleep(1)
                    continue

                resp = wallex_http.get_trades(settings.symbol)
                # Extract candidate trade list from various possible shapes
                candidates = []
                if isinstance(resp, dict):
                    for k in ("trades", "data", "result", "items"):
                        if k in resp and isinstance(resp[k], list):
                            candidates = resp[k]
                            break
                    if not candidates:
                        for v in resp.values():
                            if isinstance(v, list):
                                candidates = v
                                break
                elif isinstance(resp, list):
                    candidates = resp

                def _extract_ts(d: dict) -> int:
                    try:
                        return int(d.get("ts") or d.get("T") or d.get("t") or 0)
                    except Exception:
                        return 0

                # Sort by timestamp ascending and feed only new trades
                candidates_sorted = sorted(candidates, key=_extract_ts)
                new_count = 0
                for tr in candidates_sorted:
                    ts = _extract_ts(tr)
                    if ts and ts <= last_trade_ts:
                        continue
                    handle_trade(tr)
                    new_count += 1

                if should_poll:
                    logger.info(f"Polling fetched {new_count} new trades (total candidates={len(candidates_sorted)})")

                if new_count == 0:
                    time.sleep(settings.polling_interval_sec)
                else:
                    time.sleep(max(1, settings.polling_interval_sec // 2))
            except Exception as e:
                logger.exception(f"Polling trades failed: {e}")
                time.sleep(settings.polling_interval_sec)

    poller_thread = threading.Thread(target=polling_loop, daemon=True)
    poller_thread.start()

    # Connect WS after starting poller for immediate coverage
    ws.connect()
    ws.subscribe(f"{settings.symbol}@trade")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        stop_event.set()
        ws.disconnect()
        try:
            poller_thread.join(timeout=5)
        except Exception:
            pass


if __name__ == "__main__":
    run()