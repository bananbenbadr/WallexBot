from typing import Optional
from ..models.types import LLMDecision, OrderRequest
from ..utils.logging import get_logger

logger = get_logger(__name__)


class TradingEngine:
    def __init__(self, symbol: str, quote_amount: float):
        self.symbol = symbol
        self.quote_amount = quote_amount
        self.position = None  # 'long' | 'short' | None

    def _format_quantity(self, qty: float) -> float:
        # Basic precision control: 6 decimal places, positive only
        q = max(qty, 0.0)
        q = float(f"{q:.6f}")
        # Enforce a minimal tradable quantity
        if q < 0.000001:
            return 0.0
        return q

    def decide_order(self, price: float, decision: LLMDecision) -> Optional[OrderRequest]:
        if decision.action == "flat":
            logger.info("LLM suggests flat. No order.")
            return None
        if price <= 0:
            logger.warning("Invalid price, skipping order decision.")
            return None
        side = "BUY" if decision.action == "long" else "SELL"
        raw_qty = self.quote_amount / price
        qty = self._format_quantity(raw_qty)
        if qty <= 0:
            logger.warning("Calculated quantity too small; skipping order.")
            return None
        logger.info(f"Prepare {side} {qty} {self.symbol} at market price {price}")
        return OrderRequest(symbol=self.symbol, side=side, type="MARKET", quantity=qty)