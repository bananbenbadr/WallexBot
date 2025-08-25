import socketio
from typing import Callable, Set
from ..utils.logging import get_logger

logger = get_logger(__name__)


class WallexWSClient:
    def __init__(self, base_url: str = "https://api.wallex.ir"):
        # Enable auto-reconnect with backoff
        self.sio = socketio.Client(
            logger=False,
            engineio_logger=False,
            reconnection=True,
            reconnection_attempts=0,  # unlimited
            reconnection_delay=1,
            reconnection_delay_max=10,
        )
        self.base_url = base_url
        self._subscriptions: Set[str] = set()

        @self.sio.event
        def connect():
            logger.info("Connected to Wallex WebSocket")
            # Resubscribe to channels upon (re)connect
            for ch in list(self._subscriptions):
                try:
                    self.sio.emit("subscribe", {"channel": ch})
                    logger.info(f"Re-subscribed to {ch}")
                except Exception as e:
                    logger.exception(f"Failed to resubscribe {ch}: {e}")

        @self.sio.event
        def disconnect():
            logger.info("Disconnected from Wallex WebSocket")

        @self.sio.event
        def connect_error(data):
            logger.error(f"WebSocket connect error: {data}")

    def connect(self):
        try:
            # socket.io endpoint is the same base URL
            self.sio.connect(self.base_url, transports=["websocket"])  # socket.io
        except Exception as e:
            logger.exception(f"Initial WebSocket connection failed: {e}")
            # The client will attempt reconnections automatically

    def disconnect(self):
        if self.sio.connected:
            self.sio.disconnect()

    def on_message(self, callback: Callable[[str, dict], None]):
        def _on_message(*args):
            try:
                # Wallex may emit either (channel, data) or a single dict payload
                channel = ""
                data = None
                if len(args) == 2:
                    channel, data = args[0], args[1]
                elif len(args) == 1:
                    payload = args[0]
                    if isinstance(payload, dict):
                        channel = payload.get("channel") or payload.get("topic") or ""
                        data = payload.get("data") if "data" in payload else payload
                    else:
                        data = payload
                else:
                    logger.debug(f"Broadcaster received unexpected args: {args}")
                if data is None:
                    data = {}
                callback(channel, data)
            except Exception as e:
                logger.exception(f"Error in message callback: {e}")

        try:
            # Register explicit handler to avoid Optional decorator typing issues
            self.sio.on("Broadcaster", _on_message)
        except Exception as e:
            logger.exception(f"Failed to register Broadcaster handler: {e}")

    def subscribe(self, channel: str):
        self._subscriptions.add(channel)
        if not self.sio.connected:
            self.connect()
        try:
            self.sio.emit("subscribe", {"channel": channel})
            logger.info(f"Subscribed to {channel}")
        except Exception as e:
            logger.exception(f"Subscribe failed for {channel}: {e}")