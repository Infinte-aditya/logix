"""Notifier tests (moto only - real AWS is never touched)."""

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
    assert "[HIGH] Log anomaly" in envelope["Subject"]
    assert "error_rate" not in ALERT
    msg = envelope["Message"]
    json_part = msg[msg.rindex("\n{"):]
    assert json.loads(json_part) == ALERT
    attrs = envelope.get("MessageAttributes", {})
    assert attrs.get("severity", {}).get("Value") == "HIGH"


def test_critical_severity_is_published(notifier, queue):
    sqs, queue_url = queue
    critical = {**ALERT, "severity": "CRITICAL", "error_rate": 0.5}
    assert notifier.handle(json.dumps(critical)) is True
    envelope = json.loads(received_messages(sqs, queue_url)[0]["Body"])
    assert "[CRITICAL]" in envelope["Subject"]


def test_lower_severity_is_not_published(notifier, queue):
    sqs, queue_url = queue
    assert notifier.handle(json.dumps({**ALERT, "severity": "LOW"})) is False
    assert received_messages(sqs, queue_url) == []


def test_invalid_payload_is_skipped_without_raising(notifier):
    assert notifier.handle("this is not json{{{") is False
    assert notifier.handle('{"severity": "WAT"}') is False


def test_duplicate_severity_window_is_suppressed(notifier, queue):
    sqs, queue_url = queue
    assert notifier.handle(json.dumps(ALERT)) is True
    first = json.loads(received_messages(sqs, queue_url)[0]["Body"])
    assert "[HIGH]" in first["Subject"]
    assert notifier.handle(json.dumps(ALERT)) is False


def test_aws_failure_does_not_raise_out_of_handler():
    flaky = FlakySNS(failures=5)
    notifier = Notifier(sns=flaky, topic_arn="arn:aws:sns:us-east-1:123456789012:t",
                        min_severity=SEVERITY_LEVEL["MEDIUM"], retry_base_delay=0)
    assert notifier.handle(json.dumps(ALERT)) is False
    assert flaky.calls == 5


def test_transient_aws_failure_is_retried_then_published():
    flaky = FlakySNS(failures=2)
    notifier = Notifier(sns=flaky, topic_arn="arn:aws:sns:us-east-1:123456789012:t",
                        min_severity=SEVERITY_LEVEL["MEDIUM"], retry_base_delay=0)
    assert notifier.handle(json.dumps(ALERT)) is True
    assert flaky.calls >= 3


def test_notifications_disabled_skips_alert(notifier, queue):
    notifier.enabled = False
    assert notifier.handle(json.dumps(ALERT)) is False


def test_apply_settings_updates_min_severity(notifier):
    notifier.apply_settings({"notify_min_severity": "HIGH", "notifications_enabled": True})
    assert notifier.min_severity == SEVERITY_LEVEL["HIGH"]


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
    assert cfg["digest_seconds"] == 0


def test_read_config_requires_topic_arn(monkeypatch):
    monkeypatch.delenv("SNS_TOPIC_ARN", raising=False)
    with pytest.raises(SystemExit):
        read_config()