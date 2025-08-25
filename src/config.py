from dataclasses import dataclass
from dotenv import load_dotenv
import os


@dataclass
class Settings:
    wallex_api_key: str = ""
    wallex_base_url: str = "https://api.wallex.ir"
    symbol: str = "BTCUSDT"
    use_llm: bool = True
    enable_pine: bool = True
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"
    trade_amount_quote: float = 10.0
    log_level: str = "INFO"
    # New flags for safety and reliability
    dry_run: bool = True
    enable_polling: bool = True
    polling_interval_sec: int = 5
    ws_idle_timeout_sec: int = 15


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        wallex_api_key=os.getenv("WALLEX_API_KEY", ""),
        wallex_base_url=os.getenv("WALLEX_BASE_URL", "https://api.wallex.ir"),
        symbol=os.getenv("TRADE_SYMBOL", "BTCUSDT"),
        use_llm=os.getenv("USE_LLM", "true").lower() == "true",
        enable_pine=os.getenv("ENABLE_PINE", "true").lower() == "true",
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
        trade_amount_quote=float(os.getenv("TRADE_AMOUNT_USDT", "10")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        dry_run=os.getenv("DRY_RUN", "true").lower() == "true",
        enable_polling=os.getenv("ENABLE_POLLING", "true").lower() == "true",
        polling_interval_sec=int(os.getenv("POLLING_INTERVAL_SEC", "5")),
        ws_idle_timeout_sec=int(os.getenv("WS_IDLE_TIMEOUT_SEC", "15")),
    )