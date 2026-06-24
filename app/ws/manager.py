import asyncio
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)

_loop: asyncio.AbstractEventLoop | None = None


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


class ConnectionManager:
    def __init__(self):
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        await ws.accept()
        self._connections[user_id].add(ws)
        logger.info("WS conectado: user=%s conexiones=%s", user_id, len(self._connections[user_id]))

    def disconnect(self, user_id: int, ws: WebSocket) -> None:
        self._connections[user_id].discard(ws)
        if not self._connections[user_id]:
            self._connections.pop(user_id, None)
        logger.info("WS desconectado: user=%s", user_id)

    async def broadcast(self, user_id: int, message: dict) -> None:
        conns = list(self._connections.get(user_id, []))
        dead = []
        for ws in conns:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(user_id, ws)

    def broadcast_from_sync(self, user_id: int, message: dict) -> None:
        """Envía un broadcast desde un handler síncrono (sin bloquear el request)."""
        if _loop is None or not _loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(user_id, message), _loop)


manager = ConnectionManager()
