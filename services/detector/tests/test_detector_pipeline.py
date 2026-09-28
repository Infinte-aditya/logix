import uuid

import jsonschema

from app.main import COOLDOWN_SECONDS, Detector, load_config


def test_steady_traffic_never_alerts(feed):
    feed.warm_up(error_rate=0.02)
    feed.step(0.02, seconds=90)
    assert feed.alerts == []


def test_warmup_emits_nothing_even_on_spike(feed):
    feed.step(0.60, seconds=119)
    assert feed.alerts == []


def test_spike_after_warmup_alerts_at_high_or_above(feed):
    feed.warm_up(error_rate=0.02)
    feed.step(0.40, seconds=60)
    assert feed.alerts, "expected alerts from a 40% spike"
    top = max(feed.alerts, key=lambda a: a["z_score"])
    assert top["severity"] == "CRITICAL"
    assert top["z_score"] >= 9.0


def test_spike_publishes_full_escalation_chain_immediately(feed):
    feed.warm_up(error_rate=0.02)
    feed.step(0.40, seconds=60)
    severities = [a["severity"] for a in feed.alerts]
    assert severities[:4] == ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert all(s == "CRITICAL" for s in severities[4:])  # only cooldown re-publishes


def test_same_severity_suppressed_within_cooldown(make_detector):
    detector = make_detector(start_ts=0.0)
    detector.baseline.mean = 0.02
    detector.baseline._var = 0.0

    def fill_window(end_tick):
        detector.window.events.clear()
        for i in range(600):
            detector.process_event(end_tick - 60.0 + i * 0.1, i % 20 == 0)  # 5% errors

    fill_window(181.0)
    first = detector.tick(181.0)
    assert first["severity"] == "LOW"
    mid = 181.0 + COOLDOWN_SECONDS / 2
    fill_window(mid)
    assert detector.tick(mid) is None  # same severity inside 30s cooldown
    fill_window(181.0 + COOLDOWN_SECONDS)
    repeat = detector.tick(181.0 + COOLDOWN_SECONDS)
    assert repeat is not None and repeat["severity"] == "LOW"  # 30s elapsed


def test_baseline_not_updated_while_anomaly_active(feed):
    feed.warm_up(error_rate=0.02)
    feed.step(0.40, seconds=60)
    assert feed.detector.anomaly_active
    frozen_mean = feed.alerts[0]["baseline_mean"]
    frozen_std = feed.alerts[0]["baseline_std"]
    assert feed.detector.baseline.mean == frozen_mean
    assert feed.detector.baseline.std == frozen_std
    feed.step(0.02, seconds=70)
    assert not feed.detector.anomaly_active
    assert feed.detector.baseline.mean != frozen_mean


def test_ignores_windows_under_min_events(make_detector):
    detector = make_detector(start_ts=0.0)
    detector.warmup_end = 0.0
    for i in range(19):
        detector.process_event(float(i), True)
    assert detector.tick(100.0) is None


def test_alerts_validate_against_contract(feed, schema):
    feed.detector.id_factory = uuid.uuid4
    feed.warm_up(error_rate=0.02)
    feed.step(0.40, seconds=60)
    assert feed.alerts
    validator = jsonschema.Draft7Validator(
        schema, format_checker=jsonschema.FormatChecker()
    )
    for alert in feed.alerts:
        validator.validate(alert)


def test_load_config_reads_env():
    env = {
        "LOG_PATH": "/tmp/x.log",
        "REDIS_URL": "redis://redis:6379/0",
        "ALERT_CHANNEL": "alerts-test",
        "WINDOW_SECONDS": "30",
        "ALPHA": "0.1",
    }
    assert load_config(env) == {
        "log_path": "/tmp/x.log",
        "redis_url": "redis://redis:6379/0",
        "alert_channel": "alerts-test",
        "window_seconds": 30.0,
        "alpha": 0.1,
    }


def test_detector_defaults_match_contract():
    detector = Detector(60.0, 0.05, start_ts=0.0)
    assert detector.window.window_seconds == 60.0
    assert detector.window.min_events == 20
    assert detector.warmup_end == 120.0
