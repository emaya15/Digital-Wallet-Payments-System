"""In-process WebSocket connection registry.

Connections are keyed by the *authenticated* user id, so a user can only ever
receive their own notifications. `publish` is safe to call from any thread
(request handlers, background tasks, APScheduler jobs).
"""
import asyncio
import logging
import threading
from typing import Dict, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: Dict[int, Set[WebSocket]] = {}
        self._lock = threading.Lock()
        self._loop = None

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._loop = asyncio.get_running_loop()
        with self._lock:
            self._connections.setdefault(user_id, set()).add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        with self._lock:
            sockets = self._connections.get(user_id)
            if not sockets:
                return
            sockets.discard(websocket)
            if not sockets:
                self._connections.pop(user_id, None)

    def connection_count(self, user_id: int) -> int:
        with self._lock:
            return len(self._connections.get(user_id, ()))

    async def _send(self, user_id: int, payload: dict) -> None:
        with self._lock:
            sockets = list(self._connections.get(user_id, ()))
        for websocket in sockets:
            try:
                await websocket.send_json(payload)
            except Exception:  # client went away mid-send
                logger.info("Dropping dead websocket for user %s", user_id)
                self.disconnect(user_id, websocket)

    def publish(self, user_id: int, payload: dict) -> None:
        """Queue a JSON message for every open socket of ``user_id`` (thread-safe)."""
        loop = self._loop
        if loop is None or loop.is_closed() or self.connection_count(user_id) == 0:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._send(user_id, payload), loop)
        except RuntimeError:
            logger.info("Event loop unavailable; websocket message dropped")


manager = ConnectionManager()
