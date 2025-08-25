import time
import threading
from typing import List, Dict

from src.config import load_settings
from src.utils.logging import setup_logging, get_logger
from src.wallex.api_client import WallexAPIClient
from src.wallex.ws_client import WallexWSClient
from src.llm.gemini_client import GeminiClient, LLMInput
from src.models.types import LLMDecision
from src.engine.trading_engine import TradingEngine


logger = get_logger(__name__)


def test_http_endpoints(api: WallexAPIClient, symbol: str) -> Dict[str, bool]:
    results = {"markets": False, "trades": False, "depth": False, "open_orders": False}
    try:
        markets = api.get_markets()
        assert isinstance(markets, dict)
        results["markets"] = True
        logger.info(f"HTTP markets ok; keys: {list(markets.keys())[:5]}")
    except Exception as e:
        logger.exception(f"HTTP markets failed: {e}")

    try:
        trades = api.get_trades(symbol)
        assert isinstance(trades, dict)
        results["trades"] = True
        logger.info(f"HTTP trades ok; keys: {list(trades.keys())[:5]}")
    except Exception as e:
        logger.exception(f"HTTP trades failed: {e}")

    try:
        depth = api.get_market_depth(symbol)
        assert isinstance(depth, dict)
        results["depth"] = True
        logger.info(f"HTTP depth ok; keys: {list(depth.keys())[:5]}")
    except Exception as e:
        logger.exception(f"HTTP depth failed: {e}")

    try:
        oo = api.get_open_orders(symbol)
        assert isinstance(oo, dict)
        results["open_orders"] = True
        logger.info(f"HTTP open_orders ok; keys: {list(oo.keys())[:5]}")
    except Exception as e:
        logger.exception(f"HTTP open_orders failed: {e}")
    return results


def test_websocket(base_url: str, symbol: str, wait_seconds: int = 12) -> Dict[str, int]:
    ws = WallexWSClient(base_url=base_url)
    collected: List[dict] = []
    ready = threading.Event()

    def on_msg(channel: str, data: dict):
        if channel.endswith("@trade"):
            collected.append(data)
            if len(collected) >= 1:
                ready.set()

    ws.on_message(on_msg)
    ws.connect()
    ws.subscribe(f"{symbol}@trade")

    ready.wait(wait_seconds)
    ws.disconnect()
    logger.info(f"WS messages received: {len(collected)} for {symbol}")
    return {"ws_messages": len(collected)}


def test_llm_and_engine(settings) -> Dict[str, bool]:
    outcomes = {"llm": False, "engine": False, "engine_forced_long": False}

    # Synthetic minimal trades for LLM
    synthetic = [{"p": "50000", "q": "0.001"}, {"p": "50050", "q": "0.002"}, {"p": "49950", "q": "0.0015"}]

    decision: LLMDecision
    if settings.use_llm and settings.gemini_api_key:
        try:
            llm = GeminiClient(api_key=settings.gemini_api_key, model=settings.gemini_model)
            decision = llm.analyze(LLMInput(symbol=settings.symbol, timeframe="synthetic", recent_trades=synthetic))
            assert decision.action in ("long", "short", "flat")
            outcomes["llm"] = True
            logger.info(f"LLM decision: {decision}")
        except Exception as e:
            logger.exception(f"LLM analyze failed: {e}")
            decision = LLMDecision(action="flat", confidence=0.0, reason="llm_error_fallback")
    else:
        logger.info("LLM disabled or no API key; using fallback decision for engine test")
        decision = LLMDecision(action="long", confidence=0.8, reason="test_fallback")

    try:
        engine = TradingEngine(symbol=settings.symbol, quote_amount=settings.trade_amount_quote)
        price = 50000.0
        order = engine.decide_order(price, decision)
        outcomes["engine"] = True
        logger.info(f"Engine order decision: {order}")

        # Force a long to ensure non-None order path is exercised
        forced = LLMDecision(action="long", confidence=0.9, reason="forced_test")
        order2 = engine.decide_order(price, forced)
        outcomes["engine_forced_long"] = True
        logger.info(f"Engine forced-long decision: {order2}")
    except Exception as e:
        logger.exception(f"Engine decision failed: {e}")

    return outcomes


def pick_fallback_symbol(api: WallexAPIClient) -> str:
    try:
        mkts = api.get_markets()
        res = mkts.get("result") if isinstance(mkts, dict) else None
        if isinstance(res, dict):
            for key in ("symbols", "markets", "pairs", "items", "data", "list"):
                arr = res.get(key)
                if isinstance(arr, list):
                    for ent in arr:
                        if isinstance(ent, dict):
                            sym = ent.get("symbol") or ent.get("name") or ent.get("id")
                            status = ent.get("status") or ent.get("isActive")
                            if isinstance(sym, str) and (status in ("TRADING", True, "ACTIVE", "active", None)):
                                if sym.upper() in ("BTCUSDT", "USDTTMN", "ETHUSDT", "BTCIRT", "USDTIRT"):
                                    return sym.upper()
        # Default to a common high-liquidity pair for Wallex
        return "USDTTMN"
    except Exception:
        return "USDTTMN"


def main():
    setup_logging("INFO")
    settings = load_settings()
    logger.info(
        f"Settings: symbol={settings.symbol}, base_url={settings.wallex_base_url}, "
        f"use_llm={settings.use_llm}, has_wallex_key={bool(settings.wallex_api_key)}, has_gemini_key={bool(settings.gemini_api_key)}"
    )

    api = WallexAPIClient(api_key=settings.wallex_api_key, base_url=settings.wallex_base_url)

    http_results = test_http_endpoints(api, settings.symbol)

    # WebSocket tests: configured symbol, and a fallback active symbol to validate pipeline
    ws_results_primary = test_websocket(settings.wallex_base_url, settings.symbol)
    fallback_symbol = pick_fallback_symbol(api)
    if fallback_symbol != settings.symbol:
        ws_results_fallback = test_websocket(settings.wallex_base_url, fallback_symbol)
    else:
        ws_results_fallback = {"ws_messages": ws_results_primary.get("ws_messages", 0)}

    llm_engine_results = test_llm_and_engine(settings)

    summary = {
        "http": http_results,
        "ws_primary": {"symbol": settings.symbol, **ws_results_primary},
        "ws_fallback": {"symbol": fallback_symbol, **ws_results_fallback},
        "llm_engine": llm_engine_results,
    }

    logger.info(f"E2E summary: {summary}")

    # Determine overall success (non-destructive): require HTTP to pass; WS considered pass if any test gets >=1
    success = (
        http_results.get("markets")
        and http_results.get("trades")
        and http_results.get("depth")
        and http_results.get("open_orders")
        and ((ws_results_primary.get("ws_messages", 0) >= 1) or (ws_results_fallback.get("ws_messages", 0) >= 1))
    )
    if not success:
        raise SystemExit(2)


if __name__ == "__main__":
    main()