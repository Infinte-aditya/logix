"""gateway: relays Redis alert messages to browsers over WebSocket.

Forwards each valid JSON message on ALERT_CHANNEL to /ws clients, replays
the last 50 alerts to new clients. Exposes GET/PUT /settings, GET /stats,
improved /health. Env: REDIS_URL, ALERT_CHANNEL, CORS_ORIGINS.
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
from datetime import datetime, timezone
from typing import Any

import jsonschema
import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

_CONTRACTS_DIR = os.getenv("CONTRACTS_DIR", "/app/contracts")
with open(os.path.join(_CONTRACTS_DIR, "settings.schema.json")) as f:
    SETTINGS_SCHEMA = json.load(f)
DEFAULT_SETTINGS = {k: v.get("default") for k, v in SETTINGS_SCHEMA["properties"].items()}
DEFAULT_SETTINGS["severity_thresholds"] = {
    k: v["default"] for k, v in SETTINGS_SCHEMA["properties"]["severity_thresholds"]["properties"].items()
}

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


def _read_tail(path: str, n: int) -> list[str]:
    with open(path) as f:
        return list(deque(f, n))


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[WebSocket, asyncio.Lock] = {}

    @property
    def client_count(self) -> int:
        return len(self._connections)

    def connect(self, websocket: WebSocket) -> None:
        self._connections[websocket] = asyncio.Lock()

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.pop(websocket, None)

    async def send_history(self, websocket: WebSocket, history: Iterable[str]) -> None:
        lock = self._connections.get(websocket)
        if lock is None:
            return
        async with lock:
            for data in list(history):
                if not await self._send(websocket, data):
                    return

    async def broadcast(self, data: str) -> None:
        for websocket, lock in list(self._connections.items()):
            async with lock:
                if websocket in self._connections:
                    await self._send(websocket, data)

    async def _send(self, websocket: WebSocket, data: str) -> bool:
        try:
            await asyncio.wait_for(websocket.send_text(data), timeout=SEND_TIMEOUT)
        except Exception:
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
        json.loads(data)
    except (TypeError, ValueError):
        return False
    return True


async def run_subscriber(state: GatewayState) -> None:
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
        except Exception as exc:
            logger.warning("redis subscription lost (%s); retrying in %.1fs", exc, backoff)
        finally:
            if pubsub is not None:
                with suppress(Exception):
                    await pubsub.aclose()
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, BACKOFF_MAX)


async def get_settings(redis) -> dict:
    raw = await redis.get("settings:current")
    if raw:
        try:
            stored = json.loads(raw)
            merged = dict(DEFAULT_SETTINGS)
            merged.update(stored)
            return merged
        except (TypeError, ValueError):
            pass
    return dict(DEFAULT_SETTINGS)


async def validate_settings(data: dict) -> dict | None:
    try:
        jsonschema.validate(data, SETTINGS_SCHEMA)
    except jsonschema.ValidationError as e:
        return {"detail": f"Validation error: {e.message}"}
    if data.get("severity_thresholds"):
        t = data["severity_thresholds"]
        vals = [t["low"], t["medium"], t["high"], t["critical"]]
        if vals != sorted(vals):
            return {"detail": "severity_thresholds must be strictly increasing"}
    return None


def create_app(
    redis_client: Any = None,
    redis_url: str = REDIS_URL,
    channel: str = ALERT_CHANNEL,
    allowed_origins: Iterable[str] | None = None,
) -> FastAPI:
    state = GatewayState(
        redis=(
            redis_client
            if redis_client is not None
            else aioredis.from_url(redis_url, decode_responses=True)
        ),
        channel=channel,
    )
    origins = (list(allowed_origins) if allowed_origins is not None else list(CORS_ORIGINS))
    stats: dict[str, int] = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    _stats_lock = asyncio.Lock()

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
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    async def health() -> dict[str, object]:
        try:
            await asyncio.wait_for(state.redis.ping(), timeout=PING_TIMEOUT)
            redis_ok = True
        except Exception:
            redis_ok = False
        return {
            "status": "ok",
            "redis": redis_ok,
            "clients": state.manager.client_count,
        }

    @app.get("/stats")
    async def get_stats() -> dict[str, object]:
        async with _stats_lock:
            return {"severity_counts": dict(stats)}

    @app.get("/settings")
    async def read_settings() -> dict:
        return await get_settings(state.redis)

    @app.put("/settings")
    async def update_settings(body: dict) -> JSONResponse:
        error = await validate_settings(body)
        if error:
            return JSONResponse(status_code=422, content=error)
        await state.redis.set("settings:current", json.dumps(body))
        await state.redis.publish("settings:updated", json.dumps(body))
        return await get_settings(state.redis)

    @app.post("/settings/reset")
    async def reset_settings() -> dict:
        await state.redis.delete("settings:current")
        await state.redis.publish("settings:updated", json.dumps(DEFAULT_SETTINGS))
        return dict(DEFAULT_SETTINGS)

    @app.get("/notifications")
    async def get_notifications(limit: int = 50) -> list[str]:
        raw = await state.redis.lrange("notifier:deliveries", 0, limit - 1)
        return raw if raw else []

    @app.post("/notifications/test")
    async def send_test_notification() -> dict[str, object]:
        test_alert = {
            "id": "test-" + str(os.urandom(4).hex()),
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "severity": "MEDIUM",
            "error_rate": 0.25,
            "baseline_mean": 0.02,
            "baseline_std": 0.01,
            "z_score": 23.0,
            "window_seconds": 60,
            "message": "[TEST] Synthetic alert from the gateway — no action needed",
        }
        await state.redis.publish(state.channel, json.dumps(test_alert))
        return {"status": "published", "id": test_alert["id"]}

    @app.get("/logs")
    async def get_logs(lines: int = 50) -> dict[str, object]:
        path = os.getenv("LOG_PATH", "/data/app.log")
        try:
            raw = await asyncio.to_thread(_read_tail, path, lines)
            return {"lines": raw}
        except Exception as e:
            return {"lines": [], "error": str(e)}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        state.manager.connect(websocket)
        try:
            await state.manager.send_history(websocket, state.history)
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            state.manager.disconnect(websocket)

    return app

app = create_app()