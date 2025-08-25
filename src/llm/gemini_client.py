import json
import re
from dataclasses import dataclass
from typing import List
import requests
from ..models.types import LLMDecision


@dataclass
class LLMInput:
    symbol: str
    timeframe: str
    recent_trades: List[dict]


class GeminiClient:
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def _endpoint(self) -> str:
        return f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"

    def analyze(self, llm_input: LLMInput) -> LLMDecision:
        prompt = (
            f"You are a trading assistant. Analyze symbol {llm_input.symbol} with recent trades and recommend long/short/flat. "
            f"Respond in JSON with keys: action [long|short|flat], confidence [0-1], reason, stop_loss, take_profit.\n"
            f"RecentTrades: {llm_input.recent_trades[:20]}\n"
        )
        payload = {
            "contents": [
                {"parts": [{"text": prompt}]}
            ]
        }
        try:
            resp = requests.post(self._endpoint(), json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            # Extract text from candidates
            text = ""
            for cand in data.get("candidates", []):
                parts = cand.get("content", {}).get("parts", [])
                for p in parts:
                    if "text" in p:
                        text += p["text"] + "\n"
            if not text:
                return LLMDecision(action="flat", confidence=0.0, reason="No text in LLM response")
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                try:
                    obj = json.loads(m.group(0))
                    return LLMDecision(**obj)
                except Exception:
                    pass
            return LLMDecision(action="flat", confidence=0.0, reason="Could not parse LLM output")
        except requests.RequestException as e:
            return LLMDecision(action="flat", confidence=0.0, reason=f"LLM error: {e}")