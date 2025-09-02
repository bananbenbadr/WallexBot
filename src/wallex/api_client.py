import requests
from typing import Dict, List, Optional
from ..utils.logging import get_logger
from ..models.types import OrderRequest

logger = get_logger(__name__)


class WallexAPIClient:
    def __init__(self, api_key: str, base_url: str = "https://api.wallex.ir"):
        self.api_key = api_key
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            "X-API-Key": api_key,
            "Content-Type": "application/json"
        })

    def get_markets(self) -> Dict:
        """Get list of all available markets."""
        try:
            response = self.session.get(f"{self.base_url}/v1/markets")
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get markets: {e}")
            raise

    def get_market_depth(self, symbol: str) -> Dict:
        """Get order book for a specific symbol."""
        try:
            response = self.session.get(f"{self.base_url}/v1/depth", params={"symbol": symbol})
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get market depth for {symbol}: {e}")
            raise

    def get_trades(self, symbol: str) -> Dict:
        """Get recent trades for a symbol."""
        try:
            response = self.session.get(f"{self.base_url}/v1/trades", params={"symbol": symbol})
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get trades for {symbol}: {e}")
            raise

    def get_open_orders(self, symbol: Optional[str] = None) -> Dict:
        """Get open orders for account."""
        try:
            params = {"symbol": symbol} if symbol else {}
            response = self.session.get(f"{self.base_url}/v1/account/openOrders", params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get open orders: {e}")
            raise

    def place_order(self, order: OrderRequest) -> Dict:
        """Place a new order."""
        try:
            data = {
                "symbol": order.symbol,
                "side": order.side,
                "type": order.type,
                "quantity": str(order.quantity)
            }
            if order.price:
                data["price"] = str(order.price)
                
            response = self.session.post(f"{self.base_url}/v1/account/orders", json=data)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to place order: {e}")
            raise

    def cancel_order(self, order_id: str) -> Dict:
        """Cancel an existing order."""
        try:
            response = self.session.delete(f"{self.base_url}/v1/account/orders/{order_id}")
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            raise

    # --- Account endpoints for dashboard ---
    def get_account_balances(self) -> Dict:
        """Get account balances (wallet)."""
        try:
            response = self.session.get(f"{self.base_url}/v1/account/balances")
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get account balances: {e}")
            raise

    def get_account_transactions(self, limit: int = 20) -> Dict:
        """Get account transactions (e.g., deposits/withdrawals/transfers)."""
        try:
            response = self.session.get(f"{self.base_url}/v1/account/transactions", params={"limit": limit})
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get account transactions: {e}")
            raise

    def get_account_trades(self, symbol: Optional[str] = None, limit: int = 50) -> Dict:
        """Get recent account trades/fills."""
        try:
            params = {"limit": limit}
            if symbol:
                params["symbol"] = symbol
            response = self.session.get(f"{self.base_url}/v1/account/trades", params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get account trades: {e}")
            raise

    def get_account_profile(self) -> Dict:
        """Get authenticated user's profile information."""
        try:
            response = self.session.get(f"{self.base_url}/v1/account/profile")
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get account profile: {e}")
            raise