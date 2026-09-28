"""Detector service: tail LOG_PATH, score error-rate anomalies, publish alerts."""

import os
import signal
import threading
import time
import uuid

from app.baseline import Baseline
from app.publisher import RedisPublisher
from app.severity import RANK, build_alert, classify
from app.tailer import Tailer, parse_line
from app.window import SlidingWindow

TICK_SECONDS = 1.0
WARMUP_SECONDS = 120.0
COOLDOWN_SECONDS = 30.0
MIN_EVENTS = 20
ALPHA_DEFAULT = 0.05
LOG_PATH_DEFAULT = "/data/app.log"
CHANNEL_DEFAULT = "alerts"
REDIS_URL_DEFAULT = "redis://localhost:6379/0"


def load_config(environ=None):
    env = environ if environ is not None else os.environ
    return {
        "log_path": env.get("LOG_PATH", LOG_PATH_DEFAULT),
        "redis_url": env.get("REDIS_URL", REDIS_URL_DEFAULT),
        "alert_channel": env.get("ALERT_CHANNEL", CHANNEL_DEFAULT),
        "window_seconds": float(env.get("WINDOW_SECONDS", "60")),
        "alpha": float(env.get("ALPHA", str(ALPHA_DEFAULT))),
    }


class Detector:
    """Pure pipeline: window -> warm-up -> baseline -> severity -> cooldown."""

    def __init__(self, window_seconds, alpha, start_ts, id_factory=uuid.uuid4):
        self.window = SlidingWindow(window_seconds, MIN_EVENTS)
        self.baseline = Baseline(alpha)
        self.window_seconds = window_seconds
        self.warmup_end = start_ts + WARMUP_SECONDS
        self.id_factory = id_factory
        self.anomaly_active = False
        self._last_severity = None
        self._last_publish_ts = None

    def process_event(self, timestamp, is_error):
        self.window.add(timestamp, is_error)

    def tick(self, now):
        """Advance one tick; return an alert payload or None."""
        self.window.evict(now)
        rate = self.window.error_rate()
        if rate is None:
            return None
        if now < self.warmup_end:
            self.baseline.update(rate)
            return None
        z, severity = classify(rate, self.baseline)
        if severity is None:
            self.anomaly_active = False
            self.baseline.update(rate)
            return None
        self.anomaly_active = True
        if not self._should_publish(severity, now):
            return None
        self._last_severity = severity
        self._last_publish_ts = now
        return build_alert(
            self.id_factory(),
            now,
            z,
            severity,
            rate,
            self.baseline,
            self.window_seconds,
        )

    def _should_publish(self, severity, now):
        if self._last_severity is None:
            return True
        escalated = RANK[severity] > RANK[self._last_severity]
        return escalated or now - self._last_publish_ts >= COOLDOWN_SECONDS


def run_detector(detector, tailer, publisher, stop):
    next_tick = time.time()
    for lines in tailer.follow(stop):
        for line in lines:
            event = parse_line(line)
            if event is not None:
                detector.process_event(*event)
        now = time.time()
        if now >= next_tick:
            next_tick = now + TICK_SECONDS
            alert = detector.tick(now)
            if alert is not None:
                print(
                    f"[detector] {alert['severity']} z={alert['z_score']:.1f}",
                    flush=True,
                )
                publisher.publish(alert)


def main():
    cfg = load_config()
    if cfg["window_seconds"] <= 0 or not 0 < cfg["alpha"] < 1:
        print("[detector] WINDOW_SECONDS must be > 0 and ALPHA in (0, 1)", flush=True)
        return 1
    stop = threading.Event()

    def handle_signal(signum, frame):
        stop.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    print(
        f"[detector] tailing {cfg['log_path']} -> channel {cfg['alert_channel']}",
        flush=True,
    )
    detector = Detector(cfg["window_seconds"], cfg["alpha"], start_ts=time.time())
    publisher = RedisPublisher(cfg["redis_url"], cfg["alert_channel"])
    run_detector(detector, Tailer(cfg["log_path"]), publisher, stop)
    print("[detector] stopped cleanly", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
