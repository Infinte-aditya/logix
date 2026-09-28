import json

import pytest
import redis

from app.publisher import MAX_DELAY, RedisPublisher


class FlakyRedis:
    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.published = []

    def publish(self, channel, payload):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise redis.RedisError("connection refused")
        self.published.append((channel, payload))


def make_publisher(fail_times, retry_seconds=30.0):
    publisher = RedisPublisher("redis://localhost:6379/0", "alerts", retry_seconds)
    publisher._client = FlakyRedis(fail_times)
    return publisher


def test_publishes_json_payload(fake_clock):
    publisher = make_publisher(fail_times=0)
    alert = {"id": "alert-1", "severity": "LOW"}
    assert publisher.publish(
        alert, sleep=fake_clock.sleep, monotonic=fake_clock.monotonic
    )
    channel, payload = publisher._client.published[0]
    assert channel == "alerts"
    assert json.loads(payload) == alert
    assert fake_clock.t == 1000.0  # no retries


def test_retries_with_backoff_until_success(fake_clock):
    publisher = make_publisher(fail_times=2)
    assert publisher.publish({}, sleep=fake_clock.sleep, monotonic=fake_clock.monotonic)
    assert fake_clock.t == 1000.0 + 0.5 + 1.0  # exponential backoff delays
    assert len(publisher._client.published) == 1


def test_gives_up_when_redis_stays_down(fake_clock):
    publisher = make_publisher(fail_times=10**9, retry_seconds=2.0)
    assert not publisher.publish(
        {}, sleep=fake_clock.sleep, monotonic=fake_clock.monotonic
    )
    assert fake_clock.t >= 1000.0 + 2.0
    assert publisher._client.published == []


def test_backoff_is_capped(fake_clock):
    publisher = make_publisher(fail_times=10**9, retry_seconds=100.0)
    assert not publisher.publish(
        {}, sleep=fake_clock.sleep, monotonic=fake_clock.monotonic
    )
    assert fake_clock.t <= 1000.0 + 100.0 + MAX_DELAY


def test_non_redis_errors_propagate(fake_clock):
    class Broken:
        def publish(self, channel, payload):
            raise ValueError("bug")

    publisher = RedisPublisher("redis://localhost:6379/0", "alerts")
    publisher._client = Broken()
    with pytest.raises(ValueError):
        publisher.publish({}, sleep=fake_clock.sleep, monotonic=fake_clock.monotonic)
