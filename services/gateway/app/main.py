"""gateway: relays Redis alert messages to browsers over WebSocket (AGENTS.md).

Forwards each valid JSON message on ALERT_CHANNEL unchanged to every /ws
client, replays the last 50 alerts to new clients. Env: REDIS_URL,
ALERT_CHANNEL, CORS_ORIGINS.
"""

import asyncio
import json
import logging
import os
import sys
from collections import deque
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any

import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger("gateway")

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
ALERT_CHANNEL = os.getenv("ALERT_CHANNEL", "alerts")
_CORS_DEFAULT = "http://localhost:8080,http://localhost:5173"
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", _CORS_DEFAULT).split(",")
    if origin.strip()
]
HISTORY_SIZE = 50
SEND_TIMEOUT = 5.0
PING_TIMEOUT = 2.0
BACKOFF_INIT = 1.0
BACKOFF_MAX = 10.0


class ConnectionManager:
    """Tracks connected WebSockets and serializes sends per connection."""

    def __init__(self) -> None:
        self._connections: dict[WebSocket, asyncio.Lock] = {}

    def connect(self, websocket: WebSocket) -> None:
        self._connections[websocket] = asyncio.Lock()

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.pop(websocket, None)

    async def send_history(self, websocket: WebSocket, history: Iterable[str]) -> None:
        """Replay the backlog to one client while holding its send lock."""
        lock = self._connections.get(websocket)
        if lock is None:
            return
        async with lock:
            for data in list(history):
                if not await self._send(websocket, data):
                    return

    async def broadcast(self, data: str) -> None:
        """Send an alert to every connected client, dropping dead ones."""
        for websocket, lock in list(self._connections.items()):
            async with lock:
                if websocket in self._connections:
                    await self._send(websocket, data)

    async def _send(self, websocket: WebSocket, data: str) -> bool:
        try:
            await asyncio.wait_for(websocket.send_text(data), timeout=SEND_TIMEOUT)
        except Exception:  # noqa: BLE001 - any send failure means a dead client
            logger.debug("dropping dead websocket connection")
            self.disconnect(websocket)
            return False
        return True


@dataclass
class GatewayState:
    redis: Any
    channel: str
    manager: ConnectionManager = field(default_factory=ConnectionManager)
    history: deque[str] = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))


def is_valid_alert_payload(data: object) -> bool:
    try:
        json.loads(data)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return True


async def run_subscriber(state: GatewayState) -> None:
    """Subscribe to ALERT_CHANNEL forever; reconnect with exponential backoff."""
    backoff = BACKOFF_INIT
    while True:
        pubsub = None
        try:
            pubsub = state.redis.pubsub()
            await pubsub.subscribe(state.channel)
            logger.info("subscribed to redis channel=%s", state.channel)
            backoff = BACKOFF_INIT
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8", "replace")
                if not is_valid_alert_payload(data):
                    logger.warning("skipping invalid alert payload: %.200r", data)
                    continue
                state.history.append(data)
                await state.manager.broadcast(data)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - never crash: redis down/dropped
            logger.warning(
                "redis subscription lost (%s); retrying in %.1fs", exc, backoff
            )
        finally:
            if pubsub is not None:
                with suppress(Exception):
                    await pubsub.aclose()
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, BACKOFF_MAX)


def create_app(
    redis_client: Any = None,
    redis_url: str = REDIS_URL,
    channel: str = ALERT_CHANNEL,
    allowed_origins: Iterable[str] | None = None,
) -> FastAPI:
    """Build the app; inject redis_client in tests, else connect via redis_url."""
    state = GatewayState(
        redis=(
            redis_client
            if redis_client is not None
            else aioredis.from_url(redis_url, decode_responses=True)
        ),
        channel=channel,
    )
    origins = (
        list(allowed_origins) if allowed_origins is not None else list(CORS_ORIGINS)
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("gateway starting: channel=%s", state.channel)
        task = asyncio.create_task(run_subscriber(state))
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        logger.info("gateway stopped")

    app = FastAPI(title="gateway", lifespan=lifespan)
    app.state.gateway = state
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, object]:
        try:
            await asyncio.wait_for(state.redis.ping(), timeout=PING_TIMEOUT)
            redis_ok = True
        except Exception:  # noqa: BLE001 - health must report, never raise
            redis_ok = False
        return {"status": "ok", "redis": redis_ok}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        state.manager.connect(websocket)
        try:
            await state.manager.send_history(websocket, state.history)
            while True:
                await websocket.receive_text()  # drain client msgs; detect close
        except WebSocketDisconnect:
            pass
        finally:
            state.manager.disconnect(websocket)

    return app


app = create_app()
