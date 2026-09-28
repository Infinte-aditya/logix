"""notifier: relays Redis ALERT_CHANNEL alerts to AWS SNS."""

import json
import logging
import math
import os
import random
import signal
import sys
import threading
import time
from collections import deque
from contextlib import suppress
from datetime import datetime, timezone

import boto3
import redis
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger("notifier")
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(name)s %(message)s")

SEVERITY_LEVEL = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
MAX_ATTEMPTS = 5
DEAD_LETTER_KEY = "notifier:failed"
DELIVERY_LOG_KEY = "notifier:deliveries"
DIGEST_KEY = "notifier:digest"


def parse_min_severity(value: str) -> int:
    level = SEVERITY_LEVEL.get(value.strip().upper())
    if level is None:
        logger.warning("unknown MIN_SEVERITY %r, defaulting to MEDIUM", value)
        return SEVERITY_LEVEL["MEDIUM"]
    return level


def read_config() -> dict:
    topic_arn = os.getenv("SNS_TOPIC_ARN", "")
    if not topic_arn:
        raise SystemExit("SNS_TOPIC_ARN is required")
    return {
        "redis_url": os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        "channel": os.getenv("ALERT_CHANNEL", "alerts"),
        "topic_arn": topic_arn,
        "region": os.getenv("AWS_REGION", "us-east-1"),
        "endpoint_url": os.getenv("AWS_ENDPOINT_URL") or None,
        "notifier_cooldown": int(os.getenv("NOTIFIER_COOLDOWN", "60")),
        "digest_seconds": int(os.getenv("NOTIFIER_DIGEST_SECONDS", "0")),
    }


def read_settings_from_redis(r):
    try:
        raw = r.get("settings:current")
        if raw:
            stored = json.loads(raw)
            return {
                "notify_min_severity": stored.get("notify_min_severity", "MEDIUM"),
                "notifications_enabled": stored.get("notifications_enabled", True),
            }
    except Exception:
        pass
    return {"notify_min_severity": "MEDIUM", "notifications_enabled": True}


class Notifier:
    def __init__(self, sns, topic_arn, min_severity, redis_client=None, retry_base_delay=0.5, cooldown=60, digest_seconds=0):
        self.sns = sns
        self.topic_arn = topic_arn
        self.min_severity = min_severity
        self.enabled = True
        self.redis_client = redis_client
        self.retry_base_delay = retry_base_delay
        self.cooldown = cooldown
        self.digest_seconds = digest_seconds
        self._sent_window_ids: set[str] = set()
        self._digest_buffer: list[dict] = []
        self._digest_lock = threading.Lock()
        self._digest_timer: threading.Timer | None = None

    def apply_settings(self, settings):
        self.min_severity = parse_min_severity(settings.get("notify_min_severity", "MEDIUM"))
        self.enabled = settings.get("notifications_enabled", True)
        logger.info("notifier settings updated: min_severity=%s enabled=%s",
                     settings.get("notify_min_severity"), self.enabled)

    def _log_delivery(self, alert_id, severity, status, reason=""):
        entry = json.dumps({
            "alert_id": alert_id, "severity": severity, "status": status,
            "reason": reason, "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if self.redis_client:
            self.redis_client.lpush(DELIVERY_LOG_KEY, entry)
            self.redis_client.ltrim(DELIVERY_LOG_KEY, 0, 49)

    def handle(self, payload: object) -> bool:
        try:
            alert = json.loads(payload)
        except (TypeError, ValueError):
            logger.warning("skipping invalid alert payload: %.200r", payload)
            return False
        if not isinstance(alert, dict):
            logger.warning("skipping non-dict payload")
            return False
        severity = str(alert.get("severity", "")).upper()
        level = SEVERITY_LEVEL.get(severity)
        if level is None:
            logger.warning("skipping alert with unknown severity: %.200r", payload)
            self._log_delivery(alert.get("id", "?"), severity, "skipped", "unknown severity")
            return False
        if not self.enabled:
            logger.info("notifications disabled, skipping alert %s", alert.get("id"))
            self._log_delivery(alert.get("id", "?"), severity, "skipped", "notifications disabled")
            return False
        window_key = f"{severity}:{alert.get('window_seconds', 60)}:{alert.get('baseline_mean', 0):.4f}"
        if window_key in self._sent_window_ids:
            logger.info("duplicate window %s, skipping", window_key)
            self._log_delivery(alert.get("id", "?"), severity, "skipped", "duplicate window")
            return False
        if level < self.min_severity:
            logger.info("severity=%s below min_severity, skipping", severity)
            self._log_delivery(alert.get("id", "?"), severity, "skipped", "below min severity")
            return False
        self._sent_window_ids.add(window_key)
        if len(self._sent_window_ids) > 1000:
            self._sent_window_ids = set(list(self._sent_window_ids)[-500:])
        if self.digest_seconds > 0 and level <= SEVERITY_LEVEL["MEDIUM"]:
            with self._digest_lock:
                self._digest_buffer.append(alert)
                if self._digest_timer is None:
                    self._digest_timer = threading.Timer(self.digest_seconds, self._flush_digest)
                    self._digest_timer.daemon = True
                    self._digest_timer.start()
            self._log_delivery(alert.get("id", "?"), severity, "digested")
            return True
        return self._publish_alert(alert, severity)

    def _flush_digest(self):
        with self._digest_lock:
            batch = self._digest_buffer[:]
            self._digest_buffer.clear()
            self._digest_timer = None
        if not batch:
            return
        body = "\n---\n".join(
            f"[{a['severity']}] {a.get('timestamp', '')} rate={a.get('error_rate', 0):.1%} z={a.get('z_score', 0):.1f} msg={a.get('message', '')}"
            for a in batch
        )
        kwargs = {
            "TopicArn": self.topic_arn,
            "Subject": f"[DIGEST] {len(batch)} log anomalies",
            "Message": body,
            "MessageAttributes": {"severity": {"DataType": "String", "StringValue": "DIGEST"}},
        }
        result = self._with_retries("sns digest publish", lambda: self.sns.publish(**kwargs))
        for a in batch:
            self._log_delivery(a.get("id", "?"), a.get("severity", "?"),
                               "sent" if result else "failed", "digest" if result else "digest failed")

    def _publish_alert(self, alert, severity):
        pct = alert.get("error_rate", 0) * 100
        subject = f"[{severity}] Log anomaly: {pct:.1f}% errors"
        body_lines = [
            f"Time: {alert.get('timestamp', '')}",
            f"Severity: {severity}",
            f"Error rate: {pct:.1f}%",
            f"Baseline: {alert.get('baseline_mean', 0)*100:.1f}% ± {alert.get('baseline_std', 0)*100:.1f}%",
            f"Z-score: {alert.get('z_score', 0):.1f}",
            f"Message: {alert.get('message', '')}",
            "",
            json.dumps(alert, indent=2),
        ]
        kwargs = {
            "TopicArn": self.topic_arn,
            "Subject": subject,
            "Message": "\n".join(body_lines),
            "MessageAttributes": {"severity": {"DataType": "String", "StringValue": severity}},
        }
        sent = self._with_retries("sns publish", lambda: self.sns.publish(**kwargs))
        self._log_delivery(alert.get("id", "?"), severity, "sent" if sent else "failed", "" if sent else "retries exhausted")
        return sent

    def _with_retries(self, what: str, fn):
        delay = self.retry_base_delay
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                fn()
                return True
            except (BotoCoreError, ClientError) as exc:
                if attempt == MAX_ATTEMPTS:
                    logger.error("%s failed after %d attempts: %s", what, attempt, exc)
                    return False
                jitter = random.uniform(0.5, 1.5)
                sleep_time = delay * jitter
                time.sleep(min(sleep_time, 10.0))
                delay *= 2
        return False


def consume(notifier, redis_client, channel: str, stop: threading.Event) -> None:
    pubsub = redis_client.pubsub()
    pubsub.subscribe(channel)
    pubsub.subscribe("settings:updated")
    logger.info("subscribed to redis channel=%s and settings:updated", channel)
    while not stop.is_set():
        try:
            message = pubsub.get_message(timeout=1.0)
            if message is None:
                continue
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8", "replace")
            channel_name = message.get("channel", b"").decode() if isinstance(message.get("channel"), bytes) else message.get("channel", "")
            if channel_name == "settings:updated":
                try:
                    settings = json.loads(data)
                    notifier.apply_settings(settings)
                except Exception:
                    pass
                continue
            notifier.handle(data)
        except Exception as exc:
            if stop.is_set():
                break
            logger.warning("consumer error (%s); continuing", exc)


def main() -> None:
    cfg = read_config()
    stop = threading.Event()
    redis_client = redis.Redis.from_url(cfg["redis_url"], decode_responses=True)

    def shutdown(_sig, _frame) -> None:
        stop.set()
        with suppress(Exception):
            redis_client.close()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    def aws_client(service: str):
        return boto3.client(service, region_name=cfg["region"], endpoint_url=cfg["endpoint_url"])

    settings = read_settings_from_redis(redis_client)
    notifier = Notifier(
        sns=aws_client("sns"),
        topic_arn=cfg["topic_arn"],
        min_severity=parse_min_severity(settings.get("notify_min_severity", "MEDIUM")),
        redis_client=redis_client,
        retry_base_delay=0.5,
        cooldown=cfg["notifier_cooldown"],
        digest_seconds=cfg["digest_seconds"],
    )
    notifier.enabled = settings.get("notifications_enabled", True)
    logger.info("notifier starting: topic=%s min=%s enabled=%s digest=%ss",
                cfg["topic_arn"], settings.get("notify_min_severity"),
                notifier.enabled, cfg["digest_seconds"])
    consume(notifier, redis_client, cfg["channel"], stop)


if __name__ == "__main__":
    main()