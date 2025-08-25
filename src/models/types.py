from dataclasses import dataclass
from typing import Optional, Literal


@dataclass
class LLMDecision:
    action: Literal["long", "short", "flat"]
    confidence: float
    reason: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


@dataclass
class OrderRequest:
    symbol: str
    side: Literal["BUY", "SELL"]
    type: Literal["LIMIT", "MARKET"]
    quantity: float
    price: Optional[float] = None


@dataclass
class MarketTrade:
    price: float
    quantity: float
    ts: int  # milliseconds