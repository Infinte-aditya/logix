import uuid

import jsonschema

from app.main import Detector, _DEFAULTS, load_config


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
    assert all(s == "CRITICAL" for s in severities[4:])


def test_same_severity_suppressed_within_cooldown(make_detector):
    detector = make_detector(start_ts=0.0, cooldown_seconds=30)
    detector.warmup_end = 0.0
    detector.baseline.mean = 0.02
    detector.baseline._var = 0.0

    def fill_window(end_tick):
        detector.window.events.clear()
        for i in range(600):
            detector.process_event(end_tick - 60.0 + i * 0.1, i % 20 == 0)

    fill_window(181.0)
    first = detector.tick(181.0)
    assert first is not None and first["severity"] == "LOW"
    mid = 181.0 + 15
    fill_window(mid)
    assert detector.tick(mid) is None
    fill_window(181.0 + 30)
    repeat = detector.tick(181.0 + 30)
    assert repeat is not None and repeat["severity"] == "LOW"


def test_baseline_not_updated_while_anomaly_active(feed):
    feed.warm_up(error_rate=0.02)
    feed.step(0.40, seconds=60)
    assert feed.detector.anomaly_active
    frozen_mean = feed.alerts[0]["baseline_mean"]
    frozen_std = feed.alerts[0]["baseline_std"]
    assert feed.detector.baseline.mean == frozen_mean
    feed.step(0.02, seconds=70)
    assert not feed.detector.anomaly_active
    assert feed.detector.baseline.mean != frozen_mean


def test_ignores_windows_under_min_events(make_detector):
    detector = make_detector(start_ts=0.0, min_events=20)
    detector.warmup_end = 0.0
    for i in range(19):
        detector.process_event(float(i), True)
    assert detector.tick(100.0) is None


def test_alerts_validate_against_contract(feed, schema):
    feed.detector.id_factory = uuid.uuid4
    feed.warm_up(error_rate=0.02)
    feed.step(0.40, seconds=60)
    assert feed.alerts
    validator = jsonschema.Draft7Validator(schema, format_checker=jsonschema.FormatChecker())
    for alert in feed.alerts:
        validator.validate(alert)


def test_load_config_reads_env():
    env = {
        "LOG_PATH": "/tmp/x.log",
        "REDIS_URL": "redis://redis:6379/0",
        "ALERT_CHANNEL": "alerts-test",
    }
    assert load_config(env) == {
        "log_path": "/tmp/x.log",
        "redis_url": "redis://redis:6379/0",
        "alert_channel": "alerts-test",
    }


def test_detector_defaults_match_contract(make_detector):
    detector = make_detector(start_ts=0.0)
    assert detector.window.window_seconds == 60
    assert detector.window.min_events == 20
    assert detector.warmup_end == 120.0


def test_apply_settings_updates_thresholds(make_detector):
    detector = make_detector(start_ts=0.0)
    detector.warmup_end = 0.0
    detector.baseline.mean = 0.02
    detector.baseline._var = 0.0

    def fill_5pct(end_tick):
        detector.window.events.clear()
        for i in range(600):
            detector.process_event(end_tick - 60.0 + i * 0.1, i % 20 == 0)

    fill_5pct(181.0)
    first = detector.tick(181.0)
    assert first is not None

    new_settings = dict(_DEFAULTS)
    new_settings["severity_thresholds"] = {"low": 100, "medium": 101, "high": 102, "critical": 103}
    detector.apply_settings(new_settings)
    fill_5pct(200.0)
    suppressed = detector.tick(200.0)  # no severity at z~3 with thresholds at 100
    assert suppressed is None