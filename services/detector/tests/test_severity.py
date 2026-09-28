from types import SimpleNamespace

import pytest

from app.severity import bucket, build_alert, classify


def make_baseline(mean, std):
    return SimpleNamespace(mean=mean, std=std, ready=True)


def test_bucket_boundaries():
    assert bucket(2.9) is None
    assert bucket(3.0) == "LOW"
    assert bucket(4.0) == "MEDIUM"
    assert bucket(6.0) == "HIGH"
    assert bucket(9.0) == "CRITICAL"


def test_classify_ignores_drops_below_mean():
    assert classify(0.0, make_baseline(0.02, 0.01)) == (None, None)


def test_classify_uses_std_floor():
    z, severity = classify(0.05, make_baseline(0.02, 0.0))
    assert z == pytest.approx(3.0)
    assert severity == "LOW"


def test_build_alert_payload_shape():
    alert = build_alert(
        "alert-1", 0.0, 38.0, "CRITICAL", 0.4, make_baseline(0.02, 0.01), 60.0
    )
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
    assert set(alert) == {
        "id",
        "timestamp",
        "severity",
        "error_rate",
        "baseline_mean",
        "baseline_std",
        "z_score",
        "window_seconds",
        "message",
    }
