from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request
import time
import threading
from src.utils.logging import setup_logging, get_logger
from src.wallex.ws_client import WallexWSClient
from src.llm.gemini_client import GeminiClient, LLMInput
from src.engine.trading_engine import TradingEngine

from src.config import load_settings
from src.wallex.api_client import WallexAPIClient

logger = get_logger(__name__)

# Initialize Flask app
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
app = Flask(__name__, template_folder=str(TEMPLATES_DIR))

# Initialize shared settings and client
settings = load_settings()
client = WallexAPIClient(api_key=settings.wallex_api_key, base_url=settings.wallex_base_url)

# Simple in-memory cache to mitigate provider rate limits
_depth_cache: Dict[str, Dict[str, Any]] = {}
# Account caches
_account_bal_cache: Dict[str, Any] = {"ts": 0, "data": None}
_account_tx_cache: Dict[str, Any] = {"ts": 0, "data": None}
_portfolio_cache: Dict[str, Any] = {"ts": 0, "data": None}


# ------------------------
# Helpers to normalize API
# ------------------------

def _to_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def normalize_trades(raw: Any) -> List[Dict[str, Any]]:
    # Try to find a list of trades in typical shapes
    trades: List[Any] = []
    if isinstance(raw, list):
        trades = raw
    elif isinstance(raw, dict):
        # known keys or first list value
        for k in ("trades", "data", "result", "items"):
            if k in raw and isinstance(raw[k], list):
                trades = raw[k]
                break
        if not trades:
            for v in raw.values():
                if isinstance(v, list):
                    trades = v
                    break
    out: List[Dict[str, Any]] = []
    for t in trades:
        if isinstance(t, dict):
            ts = int(t.get("ts") or t.get("T") or t.get("t") or 0)
            price_val = t.get("price") or t.get("p")
            qty_val = t.get("quantity") or t.get("q") or t.get("qty")
            out.append({
                "ts": ts,
                "price": _to_float(price_val),
                "qty": _to_float(qty_val),
                "raw": t,
            })
        elif isinstance(t, (list, tuple)) and len(t) >= 2:
            out.append({
                "ts": 0,
                "price": _to_float(t[0]),
                "qty": _to_float(t[1]),
                "raw": t,
            })
    return out


def normalize_depth(raw: Any, limit: int = 10) -> Dict[str, List[Dict[str, float]]]:
    bids: List[Any] = []
    asks: List[Any] = []
    if isinstance(raw, dict):
        bids = raw.get("bids") or raw.get("Bids") or []
        asks = raw.get("asks") or raw.get("Asks") or []

    # Shape normalization: entries may be dicts or [price, qty]
    def _norm(side: List[Any]) -> List[Dict[str, float]]:
        out: List[Dict[str, float]] = []
        for e in side:
            if isinstance(e, dict):
                p = _to_float(e.get("price") or e.get("p"))
                q = _to_float(e.get("quantity") or e.get("q") or e.get("qty"))
                out.append({"price": p, "qty": q})
            elif isinstance(e, (list, tuple)) and len(e) >= 2:
                out.append({"price": _to_float(e[0]), "qty": _to_float(e[1])})
        return out[:limit]

    return {"bids": _norm(bids), "asks": _norm(asks)}


# New normalizers for account data

def normalize_balances(raw: Any) -> List[Dict[str, Any]]:
    items: List[Any] = []
    if isinstance(raw, dict):
        for k in ("balances", "wallets", "data", "result", "items"):
            if isinstance(raw.get(k), list):
                items = raw[k]
                break
        if not items:
            # sometimes balances may be under a dictionary keyed by asset
            wallets = raw.get("wallets") or raw.get("accounts") or {}
            if isinstance(wallets, dict):
                items = [{"asset": a, **(v if isinstance(v, dict) else {"total": v})} for a, v in wallets.items()]
    elif isinstance(raw, list):
        items = raw
    out: List[Dict[str, Any]] = []
    for it in items:
        if isinstance(it, dict):
            asset = it.get("asset") or it.get("currency") or it.get("symbol") or it.get("code")
            free = _to_float(it.get("free") or it.get("available") or it.get("avail") or it.get("balance"))
            locked = _to_float(it.get("locked") or it.get("frozen") or it.get("hold"))
            total = _to_float(it.get("total"))
            if total == 0.0:
                total = free + locked
            if asset:
                out.append({"asset": str(asset).upper(), "free": free, "locked": locked, "total": total})
    # sort by total desc
    out.sort(key=lambda x: x.get("total", 0), reverse=True)
    return out


def normalize_transactions(raw: Any) -> List[Dict[str, Any]]:
    items: List[Any] = []
    if isinstance(raw, dict):
        for k in ("transactions", "data", "result", "items", "history"):
            if isinstance(raw.get(k), list):
                items = raw[k]
                break
        if not items:
            for v in raw.values():
                if isinstance(v, list):
                    items = v
                    break
    elif isinstance(raw, list):
        items = raw
    out: List[Dict[str, Any]] = []
    for it in items:
        if isinstance(it, dict):
            ts = int(it.get("ts") or it.get("time") or it.get("created_at") or it.get("timestamp") or 0)
            typ = (it.get("type") or it.get("kind") or it.get("category") or "").lower()
            asset = it.get("asset") or it.get("currency") or it.get("symbol")
            amt = _to_float(it.get("amount") or it.get("qty") or it.get("quantity"))
            status = (it.get("status") or it.get("state") or "").lower()
            txid = it.get("txid") or it.get("id") or it.get("hash")
            out.append({"ts": ts, "type": typ, "asset": asset, "amount": amt, "status": status, "txid": txid, "raw": it})
    # newest first
    out.sort(key=lambda x: x.get("ts", 0), reverse=True)
    return out


def normalize_account_trades(raw: Any) -> List[Dict[str, Any]]:
    items = normalize_trades(raw)
    out: List[Dict[str, Any]] = []
    for t in items:
        d = t.get("raw") or {}
        out.append({
            "ts": t.get("ts", 0),
            "symbol": d.get("symbol") or d.get("S") or "",
            "side": (d.get("side") or d.get("s") or "").upper(),
            "price": t.get("price", 0),
            "qty": t.get("qty", 0),
        })
    out.sort(key=lambda x: x.get("ts", 0), reverse=True)
    return out


# -----------------
# HTML UI Endpoints
# -----------------

@app.route("/", methods=["GET"])
def index():
    sym = request.args.get("symbol") or settings.symbol
    return render_template(
        "index.html",
        symbol=sym,
        app_name="Wallex Trader",
        version="0.1.0",
    )


# -----------------
# JSON API Endpoints
# -----------------

@app.route("/api/config", methods=["GET"])
def api_config():
    return jsonify({
        "symbol": settings.symbol,
        "base_url": settings.wallex_base_url,
        "poll_interval_sec": max(2, settings.polling_interval_sec),
        "use_llm": settings.use_llm,
        "dry_run": settings.dry_run,
        "enable_polling": settings.enable_polling,
        "trade_amount_quote": settings.trade_amount_quote,
    })


@app.route("/api/markets", methods=["GET"])
def api_markets():
    try:
        data = client.get_markets()
        return jsonify(data)
    except Exception as e:
        return jsonify({"detail": str(e)}), 502


@app.route("/api/trades", methods=["GET"])
def api_trades():
    sym = request.args.get("symbol") or settings.symbol
    try:
        raw = client.get_trades(sym)
        return jsonify({"symbol": sym, "trades": normalize_trades(raw)})
    except Exception as e:
        return jsonify({"detail": str(e)}), 502


@app.route("/api/depth", methods=["GET"])
def api_depth():
    sym = request.args.get("symbol") or settings.symbol
    try:
        try:
            limit = int(request.args.get("limit", 10))
        except Exception:
            limit = 10
        # Serve cached depth if fresh (to reduce 429s from provider)
        now = time.time()
        cache = _depth_cache.get(sym)
        if cache and (now - cache.get("ts", 0)) < 2:  # 2s TTL
            data = {"symbol": sym}
            data.update(cache["data"])  # already normalized
            return jsonify(data)
        raw = client.get_market_depth(sym)
        norm = normalize_depth(raw, limit=limit)
        _depth_cache[sym] = {"ts": now, "data": norm}
        data = {"symbol": sym}
        data.update(norm)
        return jsonify(data)
    except Exception as e:
        # On provider errors (e.g., 429) return last known depth if available
        cache = _depth_cache.get(sym)
        if cache:
            data = {"symbol": sym, "stale": True}
            data.update(cache["data"])
            return jsonify(data)
        # No cache yet; return an empty payload with context but 200 to avoid noisy UI failures
        return jsonify({"symbol": sym, "bids": [], "asks": [], "error": str(e)})
        return jsonify({"detail": str(e)}), 502


@app.route("/api/open-orders", methods=["GET"])
def api_open_orders():
    sym = request.args.get("symbol") or settings.symbol
    try:
        data = client.get_open_orders(sym)
        return jsonify({"symbol": sym, "open_orders": data})
    except Exception as e:
        return jsonify({"detail": str(e)}), 502


# -----------------
# Account (JSON)
# -----------------

@app.route("/api/account/balances", methods=["GET"])
def api_account_balances():
    if not settings.wallex_api_key:
        return jsonify({"error": "Wallex API key not configured"}), 503
    try:
        now = time.time()
        if _account_bal_cache["data"] and (now - _account_bal_cache["ts"]) < 30:
            return jsonify({"balances": _account_bal_cache["data"], "cached": True})
        raw = client.get_account_balances()
        norm = normalize_balances(raw)
        _account_bal_cache.update({"ts": now, "data": norm})
        return jsonify({"balances": norm})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/account/transactions", methods=["GET"])
def api_account_transactions():
    if not settings.wallex_api_key:
        return jsonify({"error": "Wallex API key not configured"}), 503
    try:
        limit = 20
        try:
            limit = max(1, min(100, int(request.args.get("limit", 20))))
        except Exception:
            pass
        now = time.time()
        cache_ok = _account_tx_cache["data"] and (now - _account_tx_cache["ts"]) < 30
        if cache_ok:
            data = _account_tx_cache["data"]
        else:
            raw = client.get_account_transactions(limit=limit)
            data = normalize_transactions(raw)
            _account_tx_cache.update({"ts": now, "data": data})
        return jsonify({"transactions": data[:limit]})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/account/trades", methods=["GET"])
def api_account_trades():
    if not settings.wallex_api_key:
        return jsonify({"error": "Wallex API key not configured"}), 503
    try:
        symbol = request.args.get("symbol") or None
        try:
            limit = max(1, min(100, int(request.args.get("limit", 50))))
        except Exception:
            limit = 50
        raw = client.get_account_trades(symbol=symbol, limit=limit)
        data = normalize_account_trades(raw)
        return jsonify({"trades": data[:limit]})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/account/portfolio", methods=["GET"])
def api_account_portfolio():
    if not settings.wallex_api_key:
        return jsonify({"error": "Wallex API key not configured"}), 503
    try:
        now = time.time()
        if _portfolio_cache["data"] and (now - _portfolio_cache["ts"]) < 30:
            return jsonify(_portfolio_cache["data"])  # contains items and totals
        # get balances first
        raw_bal = client.get_account_balances()
        balances = normalize_balances(raw_bal)
        # pick up to 5 assets with non-zero totals
        assets = [b for b in balances if b.get("total", 0) > 0]
        top_assets = assets[:5]
        items: List[Dict[str, Any]] = []
        total_usdt = 0.0
        for b in top_assets:
            asset = b["asset"]
            total = _to_float(b.get("total", 0))
            if asset.upper() == "USDT":
                price = 1.0
                sym = "USDT"
                value = total
            else:
                sym = f"{asset.upper()}USDT"
                try:
                    raw_trades = client.get_trades(sym)
                    trades = normalize_trades(raw_trades)
                    last = trades[-1]["price"] if trades else 0.0
                    price = float(last) if last else 0.0
                except Exception:
                    price = 0.0
                value = total * price if price else 0.0
            total_usdt += value
            items.append({
                "asset": asset,
                "free": b.get("free", 0),
                "locked": b.get("locked", 0),
                "total": total,
                "symbol": sym,
                "price_usdt": price,
                "value_usdt": value,
            })
        data = {"items": items, "total_value_usdt": total_usdt, "updated_ts": int(now)}
        _portfolio_cache.update({"ts": now, "data": data})
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# New: Account summary for header (name + balances)
@app.route("/api/account/summary", methods=["GET"])
def api_account_summary():
    if not settings.wallex_api_key:
        return jsonify({"error": "Wallex API key not configured"}), 503
    try:
        now = time.time()
        # Try fetch profile name from Wallex
        name = ""
        try:
            prof_raw = client.get_account_profile()
            # Attempt to extract first/last name from various shapes
            if isinstance(prof_raw, dict):
                # Common shapes: { data: { first_name, last_name } } or flat
                data = prof_raw.get("data") if isinstance(prof_raw.get("data"), dict) else prof_raw
                first_name = (data.get("first_name") if isinstance(data, dict) else None) or data.get("firstName") if isinstance(data, dict) else None
                last_name = (data.get("last_name") if isinstance(data, dict) else None) or data.get("lastName") if isinstance(data, dict) else None
                if first_name or last_name:
                    name = f"{(first_name or '').strip()} {(last_name or '').strip()}".strip()
                else:
                    # Some APIs may provide 'name' directly
                    nm = data.get("name") if isinstance(data, dict) else None
                    if isinstance(nm, str):
                        name = nm.strip()
        except Exception:
            # Fallback to configured display name
            name = settings.user_display_name or ""
        if not name:
            name = settings.user_display_name or ""

        # Balances (use cache if fresh)
        if _account_bal_cache["data"] and (now - _account_bal_cache["ts"]) < 30:
            balances = _account_bal_cache["data"]
        else:
            raw = client.get_account_balances()
            balances = normalize_balances(raw)
            _account_bal_cache.update({"ts": now, "data": balances})
        usdt_balance = 0.0
        for b in balances or []:
            if str(b.get("asset", "")).upper() == "USDT":
                usdt_balance = _to_float(b.get("total", 0))
                break
        # Total portfolio value in USDT (reuse cache or compute minimal)
        if _portfolio_cache["data"] and (now - _portfolio_cache["ts"]) < 30:
            total_usdt = _portfolio_cache["data"].get("total_value_usdt", 0.0)
            updated_ts = _portfolio_cache["data"].get("updated_ts", int(now))
        else:
            # Compute quickly similar to portfolio endpoint but without item details
            raw_bal = client.get_account_balances()
            balances2 = normalize_balances(raw_bal)
            assets = [b for b in balances2 if b.get("total", 0) > 0]
            top_assets = assets[:5]
            total_usdt = 0.0
            for b in top_assets:
                asset = b["asset"]
                total = _to_float(b.get("total", 0))
                if asset.upper() == "USDT":
                    price = 1.0
                else:
                    sym = f"{asset.upper()}USDT"
                    try:
                        raw_trades = client.get_trades(sym)
                        trades = normalize_trades(raw_trades)
                        last = trades[-1]["price"] if trades else 0.0
                        price = float(last) if last else 0.0
                    except Exception:
                        price = 0.0
                value = total * price if price else 0.0
                total_usdt += value
            updated_ts = int(now)
            _portfolio_cache.update({"ts": now, "data": {"items": [], "total_value_usdt": total_usdt, "updated_ts": updated_ts}})
        return jsonify({
            "name": name,
            "usdt_balance": usdt_balance,
            "total_value_usdt": total_usdt,
            "updated_ts": updated_ts,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502

# -----------------
# Bot Control (JSON)
# -----------------

class BotRunner:
    def __init__(self):
        self.thread: Optional[threading.Thread] = None
        self.stop_event: Optional[threading.Event] = None
        self.state: Dict[str, Any] = {"running": False, "started_at": None}

    def status(self) -> Dict[str, Any]:
        return {
            "running": bool(self.thread and self.thread.is_alive()),
            "config": {
                "symbol": settings.symbol,
                "use_llm": settings.use_llm,
                "dry_run": settings.dry_run,
                "enable_polling": settings.enable_polling,
                "polling_interval_sec": settings.polling_interval_sec,
                "trade_amount_quote": settings.trade_amount_quote,
            },
        }

    def start(self, **overrides):
        if self.thread and self.thread.is_alive():
            return False
        # Apply overrides to current settings for this session only
        if "symbol" in overrides and overrides["symbol"]:
            setattr(settings, "symbol", str(overrides["symbol"]).upper())
        if "use_llm" in overrides:
            setattr(settings, "use_llm", bool(overrides["use_llm"]))
        if "dry_run" in overrides:
            setattr(settings, "dry_run", bool(overrides["dry_run"]))
        if "enable_polling" in overrides:
            setattr(settings, "enable_polling", bool(overrides["enable_polling"]))
        if "polling_interval_sec" in overrides:
            try:
                setattr(settings, "polling_interval_sec", max(2, int(overrides["polling_interval_sec"])) )
            except Exception:
                pass
        if "trade_amount_quote" in overrides:
            try:
                setattr(settings, "trade_amount_quote", float(overrides["trade_amount_quote"]))
            except Exception:
                pass

        self.stop_event = threading.Event()

        def _run():
            setup_logging(settings.log_level)
            wallex_http = WallexAPIClient(api_key=settings.wallex_api_key, base_url=settings.wallex_base_url)
            ws = WallexWSClient(base_url=settings.wallex_base_url)
            llm = None
            if settings.use_llm and settings.gemini_api_key:
                llm = GeminiClient(api_key=settings.gemini_api_key, model=settings.gemini_model)
            engine = TradingEngine(symbol=settings.symbol, quote_amount=settings.trade_amount_quote)

            recent_trades: List[dict] = []
            last_trade_ts = 0
            last_activity = time.time()

            def handle_trade(data: dict):
                nonlocal recent_trades, last_trade_ts, last_activity
                if not isinstance(data, dict):
                    return
                try:
                    ts = int(data.get("ts") or data.get("T") or data.get("t") or 0)
                except Exception:
                    ts = 0
                price_val = data.get("price") or data.get("p")
                try:
                    price = float(price_val) if price_val is not None else 0.0
                except Exception:
                    price = 0.0
                if ts and ts <= last_trade_ts:
                    return
                if ts:
                    last_trade_ts = ts
                last_activity = time.time()
                recent_trades.append(data)
                if len(recent_trades) > 200:
                    recent_trades[:] = recent_trades[-200:]
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

            def polling_loop():
                nonlocal last_activity, last_trade_ts
                if settings.enable_polling:
                    logger.info(
                        f"Polling fallback enabled: interval={settings.polling_interval_sec}s"
                    )
                while not self.stop_event.is_set():
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

                        candidates_sorted = sorted(candidates, key=_extract_ts)
                        for tr in candidates_sorted:
                            ts = _extract_ts(tr)
                            if ts and ts <= last_trade_ts:
                                continue
                            handle_trade(tr)
                        time.sleep(settings.polling_interval_sec)
                    except Exception as e:
                        logger.exception(f"Polling trades failed: {e}")
                        time.sleep(settings.polling_interval_sec)

            poller_thread = threading.Thread(target=polling_loop, daemon=True)
            poller_thread.start()
            ws.connect()
            ws.subscribe(f"{settings.symbol}@trade")
            logger.info("Bot started.")
            try:
                while not self.stop_event.is_set():
                    time.sleep(0.5)
            finally:
                try:
                    ws.disconnect()
                except Exception:
                    pass
                try:
                    poller_thread.join(timeout=5)
                except Exception:
                    pass
                logger.info("Bot stopped.")

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        if not self.thread:
            return False
        if self.stop_event and not self.stop_event.is_set():
            self.stop_event.set()
        return True


bot_runner = BotRunner()


@app.route("/api/bot/status", methods=["GET"])
def api_bot_status():
    return jsonify(bot_runner.status())


@app.route("/api/bot/start", methods=["POST"])
def api_bot_start():
    try:
        payload = request.get_json(force=True, silent=True) or {}
        ok = bot_runner.start(**payload)
        return jsonify({"started": ok, **bot_runner.status()})
    except Exception as e:
        return jsonify({"detail": str(e)}), 400


@app.route("/api/bot/stop", methods=["POST"]) 
def api_bot_stop():
    try:
        ok = bot_runner.stop()
        return jsonify({"stopped": ok, **bot_runner.status()})
    except Exception as e:
        return jsonify({"detail": str(e)}), 400