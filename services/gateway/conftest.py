import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def pytest_configure(config):
    os.environ.setdefault("CONTRACTS_DIR", str(REPO_ROOT / "contracts"))


class FakePubSub:
    """In-memory pub/sub double: tests push raw payloads onto a queue."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.channels: list[str] = []
        self.closed = False

    async def subscribe(self, *channels: str) -> None:
        self.channels.extend(channels)

    def push(self, data: str) -> None:
        """Simulate another service publishing to the channel."""
        self.queue.put_nowait(data)

    async def listen(self) -> AsyncIterator[dict]:
        while True:
            yield {
                "type": "message",
                "channel": self.channels[0] if self.channels else "alerts",
                "data": await self.queue.get(),
            }

    async def aclose(self) -> None:
        self.closed = True


class FakeRedis:
    """Minimal redis.asyncio double: ping + pubsub + key-value + lists, no network."""

    def __init__(self) -> None:
        self.pubsub_obj = FakePubSub()
        self.ping_ok = True
        self._store: dict[str, str] = {}
        self._lists: dict[str, list[str]] = {}
        self._published_channels: list[tuple[str, str]] = []

    def pubsub(self) -> FakePubSub:
        return self.pubsub_obj

    async def ping(self) -> bool:
        if not self.ping_ok:
            raise RuntimeError("redis unreachable")
        return True

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str) -> bool:
        self._store[key] = value
        return True

    async def delete(self, key: str) -> bool:
        self._store.pop(key, None)
        return True

    async def publish(self, channel: str, message: str) -> int:
        self._published_channels.append((channel, message))
        return len(self._published_channels)

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        lst = self._lists.get(key, [])
        return lst[start:end+1] if end >= 0 else lst[start:]

    async def aclose(self) -> None:
        return None


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()
