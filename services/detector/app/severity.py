"""Pure severity mapping, deviation scoring and alert payload building."""

from datetime import datetime, timezone

MIN_STD = 0.01
RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def bucket(z):
    if z >= 9:
        return "CRITICAL"
    if z >= 6:
        return "HIGH"
    if z >= 4:
        return "MEDIUM"
    if z >= 3:
        return "LOW"
    return None


def classify(rate, baseline):
    """Return (z, severity); (None, None) unless rate exceeds the mean by >= 3 std."""
    if not baseline.ready or rate <= baseline.mean:
        return None, None
    z = (rate - baseline.mean) / max(baseline.std, MIN_STD)
    return z, bucket(z)


def format_message(rate, mean, z, severity, window_seconds):
    return (
        f"{severity} anomaly: error rate {rate:.1%} over the last "
        f"{window_seconds:g}s is {z:.1f} standard deviations above the "
        f"baseline {mean:.1%}"
    )


def build_alert(alert_id, epoch, z, severity, rate, baseline, window_seconds):
    """Alert dict matching contracts/alert.schema.json."""
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
