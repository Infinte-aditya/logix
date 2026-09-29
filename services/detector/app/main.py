"""Detector service: tail LOG_PATH, score error-rate anomalies, publish alerts."""

import json
import os
import signal
import threading
import time
import uuid

import redis

from app.baseline import Baseline
from app.publisher import RedisPublisher
from app.severity import RANK, DEFAULT_THRESHOLDS, build_alert, classify
from app.tailer import Tailer, parse_line
from app.window import SlidingWindow

TICK_SECONDS = 1.0
SETTINGS_POLL_SECONDS = 10.0
LOG_PATH_DEFAULT = "/data/app.log"
CHANNEL_DEFAULT = "alerts"
REDIS_URL_DEFAULT = "redis://localhost:6379/0"

_DEFAULTS = {
    "window_seconds": 60,
    "warmup_seconds": 120,
    "min_events": 20,
    "ewma_alpha": 0.05,
    "severity_thresholds": dict(DEFAULT_THRESHOLDS),
    "cooldown_seconds": 30,
}


def load_config(environ=None):
    env = environ if environ is not None else os.environ
    return {
        "log_path": env.get("LOG_PATH", LOG_PATH_DEFAULT),
        "redis_url": env.get("REDIS_URL", REDIS_URL_DEFAULT),
        "alert_channel": env.get("ALERT_CHANNEL", CHANNEL_DEFAULT),
    }


def read_settings_from_redis(r):
    try:
        raw = r.get("settings:current")
        if raw:
            stored = json.loads(raw)
            merged = dict(_DEFAULTS)
            merged.update(stored)
            return merged
    except Exception:
        pass
    return dict(_DEFAULTS)

class Detector:
    def __init__(self, settings, start_ts, id_factory=uuid.uuid4):
        ws = settings["window_seconds"]
        me = settings["min_events"]
        self.window = SlidingWindow(ws, me)
        self.baseline = Baseline(settings["ewma_alpha"])
        self.window_seconds = ws
        self.warmup_end = start_ts + settings["warmup_seconds"]
        self.id_factory = id_factory
        self.anomaly_active = False
        self._last_severity = None
        self._last_publish_ts = None
        self.settings = settings

    def apply_settings(self, settings):
        ws = settings["window_seconds"]
        if ws != self.window_seconds:
            self.window = SlidingWindow(ws, settings["min_events"])
            self.window_seconds = ws
        self.window.min_events = settings["min_events"]
        self.baseline.alpha = settings["ewma_alpha"]
        self.settings = settings

    @property
    def _cooldown(self):
        return self.settings.get("cooldown_seconds", 30)

    @property
    def _thresholds(self):
        return self.settings.get("severity_thresholds", DEFAULT_THRESHOLDS)

    def process_event(self, timestamp, is_error):
        self.window.add(timestamp, is_error)

    def tick(self, now):
        self.window.evict(now)
        rate = self.window.error_rate()
        if rate is None:
            return None
        if now < self.warmup_end:
            return None
        z, severity = classify(rate, self.baseline, self._thresholds)
        if severity is None:
            self.anomaly_active = False
            if z is None or z < 1.0:
                self.baseline.update(rate)
            return None
        self.anomaly_active = True
        if not self._should_publish(severity, now):
            return None
        self._last_severity = severity
        self._last_publish_ts = now
        return build_alert(self.id_factory(), now, z, severity, rate, self.baseline, self.window_seconds)

    def _should_publish(self, severity, now):
        if self._last_severity is None:
            return True
        escalated = RANK[severity] > RANK[self._last_severity]
        return escalated or now - self._last_publish_ts >= self._cooldown


def run_detector(detector, tailer, publisher, stop, settings_redis=None):
    next_tick = time.time()
    next_settings_poll = time.time() + SETTINGS_POLL_SECONDS
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
                print(f"[detector] {alert['severity']} z={alert['z_score']:.1f}", flush=True)
                publisher.publish(alert)
        if settings_redis and now >= next_settings_poll:
            next_settings_poll = now + SETTINGS_POLL_SECONDS
            try:
                settings = read_settings_from_redis(settings_redis)
                detector.apply_settings(settings)
            except Exception:
                pass


def main():
    cfg = load_config()
    stop = threading.Event()

    def handle_signal(signum, frame):
        stop.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    r = redis.Redis.from_url(cfg["redis_url"], decode_responses=True)
    settings = read_settings_from_redis(r)
    print(f"[detector] tailing {cfg['log_path']} -> channel {cfg['alert_channel']}", flush=True)
    print(f"[detector] settings: window={settings['window_seconds']}s alpha={settings['ewma_alpha']}", flush=True)
    detector = Detector(settings, start_ts=time.time())
    detector.baseline.prime(0.02, 0.01)
    publisher = RedisPublisher(cfg["redis_url"], cfg["alert_channel"])
    run_detector(detector, Tailer(cfg["log_path"]), publisher, stop, settings_redis=r)
    print("[detector] stopped cleanly", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())