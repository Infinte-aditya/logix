"""Pure severity mapping, deviation scoring and alert payload building."""

from datetime import datetime, timezone

MIN_STD = 0.01
RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
DEFAULT_THRESHOLDS = {"low": 3.0, "medium": 4.0, "high": 6.0, "critical": 9.0}


def bucket(z, thresholds=None):
    t = thresholds or DEFAULT_THRESHOLDS
    if z >= t["critical"]: return "CRITICAL"
    if z >= t["high"]: return "HIGH"
    if z >= t["medium"]: return "MEDIUM"
    if z >= t["low"]: return "LOW"
    return None


def classify(rate, baseline, thresholds=None):
    if not baseline.ready or rate <= baseline.mean:
        return None, None
    z = (rate - baseline.mean) / max(baseline.std, MIN_STD)
    return z, bucket(z, thresholds)


def format_message(rate, mean, z, severity, window_seconds):
    return (
        f"{severity} anomaly: error rate {rate:.1%} over the last "
        f"{window_seconds:g}s is {z:.1f} standard deviations above the "
        f"baseline {mean:.1%}"
    )


def build_alert(alert_id, epoch, z, severity, rate, baseline, window_seconds):
    stamp = datetime.fromtimestamp(epoch, timezone.utc).isoformat()
    return {
        "id": str(alert_id),
        "timestamp": stamp.replace("+00:00", "Z"),
        "severity": severity,
        "error_rate": rate,
        "baseline_mean": baseline.mean,
        "baseline_std": baseline.std,
        "z_score": z,
        "window_seconds": int(window_seconds),
        "message": format_message(rate, baseline.mean, z, severity, window_seconds),
    }