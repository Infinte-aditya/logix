import asyncio
from collections.abc import AsyncIterator

import pytest


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
    """Minimal redis.asyncio double: ping + pubsub, no network."""

    def __init__(self) -> None:
        self.pubsub_obj = FakePubSub()
        self.ping_ok = True

    def pubsub(self) -> FakePubSub:
        return self.pubsub_obj

    async def ping(self) -> bool:
        if not self.ping_ok:
            raise RuntimeError("redis unreachable")
        return True

    async def aclose(self) -> None:
        return None


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()
