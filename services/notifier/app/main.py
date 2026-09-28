"""notifier: relays Redis ALERT_CHANNEL alerts to AWS SNS (+ optional CW Logs).

Subject "[<SEVERITY>] Log anomaly", pretty-JSON body; only severity >= MIN_SEVERITY
is forwarded; CW_LOG_GROUP optional (one stream/day); AWS_ENDPOINT_URL targets
LocalStack; credentials from the standard AWS chain only.
"""

import json
import logging
import os
import signal
import sys
import threading
import time
from contextlib import suppress
from datetime import datetime, timezone

import boto3
import redis
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger("notifier")

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format=_LOG_FORMAT)

SEVERITY_LEVEL = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
MAX_ATTEMPTS = 3


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
        "min_severity": os.getenv("MIN_SEVERITY", "MEDIUM"),
        "region": os.getenv("AWS_REGION", "us-east-1"),
        "endpoint_url": os.getenv("AWS_ENDPOINT_URL") or None,
        "cw_log_group": os.getenv("CW_LOG_GROUP") or None,
    }


class Notifier:
    """Forwards validated alerts to SNS (+ optional CloudWatch Logs)."""

    def __init__(
        self,
        sns,
        topic_arn: str,
        min_severity: int,
        logs_client=None,
        log_group: str | None = None,
        retry_base_delay: float = 0.5,
    ) -> None:
        self.sns = sns
        self.topic_arn = topic_arn
        self.min_severity = min_severity
        self.logs_client = logs_client
        self.log_group = log_group
        self.retry_base_delay = retry_base_delay
        self._cw_day = ""

    def handle(self, payload: object) -> bool:
        """Validate one alert and forward it to the sinks. Never raises."""
        try:
            alert = json.loads(payload)
        except (TypeError, ValueError):
            logger.warning("skipping invalid alert payload: %.200r", payload)
            return False
        severity = (alert.get("severity") or "") if isinstance(alert, dict) else ""
        severity = str(severity).upper()
        level = SEVERITY_LEVEL.get(severity)
        if level is None:
            logger.warning("skipping alert with unknown severity: %.200r", payload)
            return False
        if level < self.min_severity:
            logger.info("severity=%s below MIN_SEVERITY, skipping", severity)
            return False
        kwargs = {
            "TopicArn": self.topic_arn,
            "Subject": f"[{severity}] Log anomaly",
            "Message": json.dumps(alert, indent=2),
        }
        sent = self._with_retries("sns publish", lambda: self.sns.publish(**kwargs))
        if self.logs_client is not None and self.log_group:
            sent = sent and self._with_retries(
                "cloudwatch emit", lambda: self._emit_cw(kwargs["Message"])
            )
        return sent

    def _with_retries(self, what: str, fn) -> bool:
        """Run fn with up to MAX_ATTEMPTS tries and exponential backoff."""
        delay = self.retry_base_delay
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                fn()
                return True
            except (BotoCoreError, ClientError) as exc:
                if attempt == MAX_ATTEMPTS:
                    logger.error("%s failed after %d attempts: %s", what, attempt, exc)
                    return False
                time.sleep(delay)
                delay *= 2
        return False

    def _emit_cw(self, body: str) -> None:
        day = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        if day != self._cw_day:  # one log stream per day, created lazily
            try:
                self.logs_client.create_log_stream(
                    logGroupName=self.log_group, logStreamName=day
                )
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code != "ResourceAlreadyExistsException":
                    raise
            self._cw_day = day
        event = {"timestamp": int(time.time() * 1000), "message": body}
        self.logs_client.put_log_events(
            logGroupName=self.log_group, logStreamName=day, logEvents=[event]
        )


def consume(notifier, redis_client, channel: str, stop: threading.Event) -> None:
    """Subscribe to ALERT_CHANNEL forever; reconnect with backoff, never crash."""
    backoff = 1.0
    while not stop.is_set():
        pubsub = None
        try:
            pubsub = redis_client.pubsub()
            pubsub.subscribe(channel)
            logger.info("subscribed to redis channel=%s", channel)
            backoff = 1.0
            for message in pubsub.listen():
                if stop.is_set():
                    break
                if message.get("type") == "message":
                    notifier.handle(message.get("data"))
        except Exception as exc:  # noqa: BLE001 - never crash the consumer loop
            if stop.is_set():
                break
            logger.warning("redis lost (%s); retrying in %.1fs", exc, backoff)
            if stop.wait(backoff):
                break
            backoff = min(backoff * 2, 10.0)
        finally:
            if pubsub is not None:
                with suppress(Exception):
                    pubsub.close()


def main() -> None:
    cfg = read_config()
    stop = threading.Event()
    redis_client = redis.Redis.from_url(cfg["redis_url"], decode_responses=True)

    def shutdown(_sig, _frame) -> None:
        stop.set()
        with suppress(Exception):
            redis_client.close()  # unblocks the blocking pubsub.listen()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    def aws_client(service: str):
        return boto3.client(
            service, region_name=cfg["region"], endpoint_url=cfg["endpoint_url"]
        )

    notifier = Notifier(
        sns=aws_client("sns"),
        topic_arn=cfg["topic_arn"],
        min_severity=parse_min_severity(cfg["min_severity"]),
        logs_client=aws_client("logs") if cfg["cw_log_group"] else None,
        log_group=cfg["cw_log_group"],
    )
    logger.info(
        "notifier starting: channel=%s topic=%s min=%s sinks=%s",
        cfg["channel"],
        cfg["topic_arn"],
        cfg["min_severity"],
        f"endpoint={cfg['endpoint_url'] or 'aws'} cw={cfg['cw_log_group'] or 'off'}",
    )
    consume(notifier, redis_client, cfg["channel"], stop)


if __name__ == "__main__":
    main()
