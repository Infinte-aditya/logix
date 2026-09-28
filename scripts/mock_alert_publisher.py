"""Dev-only mock publisher.

Publishes contracts/sample_alert.json to the Redis `alerts` channel every 3
seconds, cycling through the four severity values. Exists so gateway/frontend/
notifier work can be developed before the detector is built.

Usage:
    pip install -r scripts/requirements.txt
    REDIS_URL=redis://localhost:6379/0 python3 scripts/mock_alert_publisher.py

Config comes from env vars (see .env.example): REDIS_URL, ALERT_CHANNEL.
"""

import json
import os
import signal
import time
from pathlib import Path

import redis

SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
INTERVAL_SECONDS = 3

running = True


def handle_sigterm(_sig, _frame):
    global running
    running = False


def main() -> None:
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    channel = os.environ.get("ALERT_CHANNEL", "alerts")

    sample_path = Path(__file__).resolve().parent.parent / "contracts" / "sample_alert.json"
    alert = json.loads(sample_path.read_text())

    client = redis.Redis.from_url(redis_url, decode_responses=True)
    print(f"mock publisher: channel={channel} url={redis_url}", flush=True)

    i = 0
    while running:
        alert["severity"] = SEVERITIES[i % len(SEVERITIES)]
        client.publish(channel, json.dumps(alert))
        print(f"published severity={alert['severity']}", flush=True)
        i += 1
        time.sleep(INTERVAL_SECONDS)

    print("mock publisher: stopping", flush=True)


if __name__ == "__main__":
    main()
