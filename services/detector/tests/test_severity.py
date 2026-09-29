from types import SimpleNamespace

import pytest

from app.severity import DEFAULT_THRESHOLDS, bucket, build_alert, classify


def make_baseline(mean, std):
    return SimpleNamespace(mean=mean, std=std, ready=True)


def test_bucket_boundaries():
    assert bucket(2.9) is None
    assert bucket(3.0) == "LOW"
    assert bucket(4.0) == "MEDIUM"
    assert bucket(6.0) == "HIGH"
    assert bucket(9.0) == "CRITICAL"


def test_bucket_custom_thresholds():
    t = {"low": 2, "medium": 5, "high": 8, "critical": 10}
    assert bucket(1.9, t) is None
    assert bucket(2.0, t) == "LOW"
    assert bucket(5.0, t) == "MEDIUM"
    assert bucket(8.0, t) == "HIGH"
    assert bucket(10.0, t) == "CRITICAL"


def test_classify_ignores_drops_below_mean():
    assert classify(0.0, make_baseline(0.02, 0.01)) == (None, None)


def test_classify_uses_std_floor():
    z, severity = classify(0.05, make_baseline(0.02, 0.0))
    assert z == pytest.approx(3.0)
    assert severity == "LOW"


def test_classify_custom_thresholds():
    t = {"low": 10, "medium": 20, "high": 30, "critical": 40}
    z, severity = classify(0.05, make_baseline(0.02, 0.001), t)
    assert severity is None


def test_build_alert_payload_shape():
    alert = build_alert("alert-1", 0.0, 38.0, "CRITICAL", 0.4, make_baseline(0.02, 0.01), 60.0)
    assert alert["id"] == "alert-1"
    assert alert["timestamp"] == "1970-01-01T00:00:00Z"
    assert alert["severity"] == "CRITICAL"
    assert alert["error_rate"] == 0.4
    assert alert["baseline_mean"] == 0.02
    assert alert["baseline_std"] == 0.01
    assert alert["z_score"] == 38.0
    assert alert["window_seconds"] == 60
    assert "CRITICAL anomaly" in alert["message"]
    assert "40.0%" in alert["message"]
    assert set(alert) == {"id", "timestamp", "severity", "error_rate", "baseline_mean", "baseline_std", "z_score", "window_seconds", "message"}


def test_changing_thresholds_changes_severity_for_same_input():
    t_loose = {"low": 10, "medium": 20, "high": 30, "critical": 40}
    baseline = make_baseline(0.02, 0.001)
    z, severity = classify(0.05, baseline, t_loose)
    assert severity is None

    t_tight = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    z2, severity2 = classify(0.05, baseline, t_tight)
    assert severity2 is not None
    assert z == z2