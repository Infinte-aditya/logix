"""Redis publisher with bounded exponential-backoff retries."""

import json
import time

import redis

INITIAL_DELAY = 0.5
MAX_DELAY = 5.0


class RedisPublisher:
    """Publishes alert dicts as JSON; survives Redis outages without crashing."""

    def __init__(self, url, channel, retry_seconds=30.0):
        self.channel = channel
        self.retry_seconds = retry_seconds
        self._client = redis.Redis.from_url(url, decode_responses=True)

    def publish(self, alert, sleep=time.sleep, monotonic=time.monotonic):
        """Publish one alert. Returns True on success, False if Redis stayed down."""
        payload = json.dumps(alert)
        delay = INITIAL_DELAY
        deadline = monotonic() + self.retry_seconds
        while True:
            try:
                self._client.publish(self.channel, payload)
                return True
            except redis.RedisError as exc:
                print(f"[publisher] publish failed ({exc}); retrying", flush=True)
                if monotonic() >= deadline:
                    print(
                        "[publisher] Redis down too long; dropping this alert",
                        flush=True,
                    )
                    return False
                sleep(delay)
                delay = min(delay * 2, MAX_DELAY)
