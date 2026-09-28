"""Gateway tests: health, broadcast fan-out, late-joiner history, bad payloads.

Uses a mocked pub/sub (FakeRedis/FakePubSub from conftest) driven in-process,
so tests are deterministic and never touch a real Redis.
"""

import asyncio
from contextlib import suppress

import httpx
import pytest
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

from app.main import create_app, run_subscriber

ALERT = '{"id":"a1","severity":"HIGH"}'
TIMEOUT = 5.0


def make_gateway(fake_redis):
    """Build the app and start the subscriber task (no lifespan needed)."""
    app = create_app(redis_client=fake_redis, allowed_origins=["http://t"])
    task = asyncio.create_task(run_subscriber(app.state.gateway))
    return app, task


async def stop_gateway(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


@pytest.mark.anyio
async def test_health_reports_redis_up(fake_redis):
    app = create_app(redis_client=fake_redis, allowed_origins=[])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gw"
    ) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "redis": True}


@pytest.mark.anyio
async def test_health_reports_redis_down(fake_redis):
    fake_redis.ping_ok = False
    app = create_app(redis_client=fake_redis, allowed_origins=[])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gw"
    ) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "redis": False}


@pytest.mark.anyio
async def test_two_clients_receive_published_alert(fake_redis):
    app, task = make_gateway(fake_redis)
    try:
        async with (
            httpx.AsyncClient(
                transport=ASGIWebSocketTransport(app), base_url="http://gw"
            ) as client,
            aconnect_ws("/ws", client) as ws1,
            aconnect_ws("/ws", client) as ws2,
        ):
            fake_redis.pubsub_obj.push(ALERT)
            got1 = await asyncio.wait_for(ws1.receive_text(), TIMEOUT)
            got2 = await asyncio.wait_for(ws2.receive_text(), TIMEOUT)
        assert got1 == ALERT
        assert got2 == ALERT
    finally:
        await stop_gateway(task)


@pytest.mark.anyio
async def test_late_joiner_receives_history(fake_redis):
    app, task = make_gateway(fake_redis)
    try:
        async with httpx.AsyncClient(
            transport=ASGIWebSocketTransport(app), base_url="http://gw"
        ) as client:
            fake_redis.pubsub_obj.push(ALERT)
            while not app.state.gateway.history:
                await asyncio.sleep(0.01)
            async with aconnect_ws("/ws", client) as late_joiner:
                got = await asyncio.wait_for(late_joiner.receive_text(), TIMEOUT)
        assert got == ALERT
    finally:
        await stop_gateway(task)


@pytest.mark.anyio
async def test_invalid_payload_is_skipped_without_crashing(fake_redis):
    app, task = make_gateway(fake_redis)
    try:
        async with (
            httpx.AsyncClient(
                transport=ASGIWebSocketTransport(app), base_url="http://gw"
            ) as client,
            aconnect_ws("/ws", client) as ws,
        ):
            fake_redis.pubsub_obj.push("this is not json{{{")
            fake_redis.pubsub_obj.push(ALERT)
            got = await asyncio.wait_for(ws.receive_text(), TIMEOUT)
        assert got == ALERT  # invalid payload skipped, loop still alive
    finally:
        await stop_gateway(task)


@pytest.mark.anyio
async def test_history_keeps_last_50(fake_redis):
    app, task = make_gateway(fake_redis)
    try:
        async with httpx.AsyncClient(
            transport=ASGIWebSocketTransport(app), base_url="http://gw"
        ) as client:
            for i in range(55):
                fake_redis.pubsub_obj.push(f'{{"n":{i}}}')
            while len(app.state.gateway.history) < 50:
                await asyncio.sleep(0.01)
            async with aconnect_ws("/ws", client) as ws:
                first = await asyncio.wait_for(ws.receive_text(), TIMEOUT)
                rest = [
                    await asyncio.wait_for(ws.receive_text(), TIMEOUT)
                    for _ in range(49)
                ]
        assert first == '{"n":5}'
        assert rest == [f'{{"n":{i}}}' for i in range(6, 55)]
    finally:
        await stop_gateway(task)
