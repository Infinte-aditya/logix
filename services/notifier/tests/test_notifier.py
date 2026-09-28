"""Notifier tests (moto only - real AWS is never touched): severity filter,
SNS delivery, retry behavior, CloudWatch sink, config parsing.
"""

import json

import boto3
import pytest

from app.main import SEVERITY_LEVEL, Notifier, parse_min_severity, read_config
from conftest import ALERT, FlakySNS, received_messages


def test_alert_at_or_above_min_severity_is_published(notifier, queue):
    sqs, queue_url = queue
    assert notifier.handle(json.dumps(ALERT)) is True
    messages = received_messages(sqs, queue_url)
    assert len(messages) == 1
    envelope = json.loads(messages[0]["Body"])
    assert envelope["Subject"] == "[HIGH] Log anomaly"
    assert envelope["Message"] == json.dumps(ALERT, indent=2)
    assert json.loads(envelope["Message"]) == ALERT


def test_critical_severity_is_published(notifier, queue):
    sqs, queue_url = queue
    critical = {**ALERT, "severity": "CRITICAL"}
    assert notifier.handle(json.dumps(critical)) is True
    envelope = json.loads(received_messages(sqs, queue_url)[0]["Body"])
    assert envelope["Subject"] == "[CRITICAL] Log anomaly"


def test_lower_severity_is_not_published(notifier, queue):
    sqs, queue_url = queue
    assert notifier.handle(json.dumps({**ALERT, "severity": "LOW"})) is False
    assert received_messages(sqs, queue_url) == []


def test_invalid_payload_is_skipped_without_raising(notifier):
    assert notifier.handle("this is not json{{{") is False
    assert notifier.handle('{"severity": "WAT"}') is False


def test_aws_failure_does_not_raise_out_of_handler():
    flaky = FlakySNS(failures=3)
    notifier = Notifier(
        sns=flaky,
        topic_arn="arn:aws:sns:us-east-1:123456789012:t",
        min_severity=SEVERITY_LEVEL["MEDIUM"],
        retry_base_delay=0,
    )
    assert notifier.handle(json.dumps(ALERT)) is False
    assert flaky.calls == 3  # gave up after MAX_ATTEMPTS, logged, continued


def test_transient_aws_failure_is_retried_then_published():
    flaky = FlakySNS(failures=2)
    notifier = Notifier(
        sns=flaky,
        topic_arn="arn:aws:sns:us-east-1:123456789012:t",
        min_severity=SEVERITY_LEVEL["MEDIUM"],
        retry_base_delay=0,
    )
    assert notifier.handle(json.dumps(ALERT)) is True
    assert flaky.calls == 3


def test_cloudwatch_sink_writes_events(aws_env):
    logs = boto3.client("logs", region_name="us-east-1")
    logs.create_log_group(logGroupName="/logix/alerts")
    notifier = Notifier(
        sns=FlakySNS(failures=0),
        topic_arn="arn:aws:sns:us-east-1:123456789012:t",
        min_severity=SEVERITY_LEVEL["MEDIUM"],
        logs_client=logs,
        log_group="/logix/alerts",
        retry_base_delay=0,
    )
    assert notifier.handle(json.dumps(ALERT)) is True
    streams = logs.describe_log_streams(logGroupName="/logix/alerts")["logStreams"]
    assert len(streams) == 1
    events = logs.get_log_events(
        logGroupName="/logix/alerts", logStreamName=streams[0]["logStreamName"]
    )["events"]
    assert json.loads(events[0]["message"]) == ALERT


def test_severity_ordering():
    order = [SEVERITY_LEVEL[s] for s in ("LOW", "MEDIUM", "HIGH", "CRITICAL")]
    assert order == sorted(order)


def test_parse_min_severity():
    assert parse_min_severity("high") == 2
    assert parse_min_severity(" LOW ") == 0
    assert parse_min_severity("bogus") == SEVERITY_LEVEL["MEDIUM"]


def test_read_config_defaults(monkeypatch):
    monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:1:t")
    cfg = read_config()
    assert cfg["channel"] == "alerts"
    assert cfg["min_severity"] == "MEDIUM"
    assert cfg["endpoint_url"] is None
    assert cfg["cw_log_group"] is None


def test_read_config_requires_topic_arn(monkeypatch):
    monkeypatch.delenv("SNS_TOPIC_ARN", raising=False)
    with pytest.raises(SystemExit):
        read_config()
