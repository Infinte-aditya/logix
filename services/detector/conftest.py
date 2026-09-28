import itertools
import json
import threading
from pathlib import Path

import pytest

from app.main import WARMUP_SECONDS, Detector

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def schema():
    with open(REPO_ROOT / "contracts" / "alert.schema.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def uuid_ids():
    return itertools.count()


@pytest.fixture
def make_detector(uuid_ids):
    def _make(start_ts=0.0, window_seconds=60.0, alpha=0.05):
        return Detector(
            window_seconds,
            alpha,
            start_ts=start_ts,
            id_factory=lambda: f"alert-{next(uuid_ids)}",
        )

    return _make


class Feed:
    """Deterministic harness: N events per second at an exact error fraction."""

    def __init__(self, detector, lines_per_sec=10):
        self.detector = detector
        self.lps = lines_per_sec
        self.t = 0.0
        self._credit = 0.0
        self.alerts = []
        self.alert_ticks = []

    def step(self, error_rate, seconds=1):
        for _ in range(seconds):
            t0 = self.t
            self.t += 1
            for i in range(self.lps):
                self._credit += error_rate
                is_error = self._credit >= 1.0
                if is_error:
                    self._credit -= 1.0
                self.detector.process_event(t0 + i / self.lps, is_error)
            alert = self.detector.tick(self.t)
            if alert is not None:
                self.alerts.append(alert)
                self.alert_ticks.append(self.t)
        return self.alerts[-1] if self.alerts else None

    def warm_up(self, error_rate=0.02):
        self.step(error_rate, seconds=int(WARMUP_SECONDS))


@pytest.fixture
def feed(make_detector):
    return Feed(make_detector())


@pytest.fixture
def stop():
    return threading.Event()


@pytest.fixture
def noop_sleep():
    return lambda _seconds: None


@pytest.fixture
def fake_clock():
    class FakeClock:
        def __init__(self):
            self.t = 1000.0

        def monotonic(self):
            return self.t

        def sleep(self, seconds):
            self.t += seconds

    return FakeClock()
