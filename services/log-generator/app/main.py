import os
import random
import signal
import threading
import time
from datetime import datetime, timezone

LOG_PATH_DEFAULT = "/data/app.log"
MAX_FILE_BYTES = 50 * 1024 * 1024
NORMAL_ERROR_RATE = 0.02
WARN_RATE = 0.08
SPIKE_ERROR_MIN = 0.15
SPIKE_ERROR_MAX = 0.60

SERVICES = ("auth", "payments", "search", "inventory", "session", "notifications")

MESSAGE_POOLS = {
    "INFO": (
        "request handled in 12ms",
        "cache hit for key user:profile",
        "background job completed",
        "health check passed",
        "user authenticated successfully",
        "session refreshed",
        "payment transaction approved",
    ),
    "WARN": (
        "response time above threshold",
        "retrying upstream call, attempt 2",
        "queue backlog growing",
        "memory usage at 82%",
        "connection pool near capacity",
    ),
    "ERROR": (
        "upstream timeout after 5000ms",
        "database connection failed",
        "unhandled exception in request handler",
        "payment declined by processor",
        "failed to publish event, dropping message",
    ),
}


def format_ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def pick_level(rng, error_rate):
    warn_rate = WARN_RATE * (1.0 - error_rate)
    r = rng.random()
    if r < error_rate:
        return "ERROR"
    if r < error_rate + warn_rate:
        return "WARN"
    return "INFO"


def load_config(environ=None):
    env = environ if environ is not None else os.environ
    return {
        "log_path": env.get("LOG_PATH", LOG_PATH_DEFAULT),
        "lines_per_sec": float(env.get("LINES_PER_SEC", "10")),
        "spike_min_interval": float(env.get("SPIKE_MIN_INTERVAL", "60")),
        "spike_max_interval": float(env.get("SPIKE_MAX_INTERVAL", "120")),
        "spike_duration": float(env.get("SPIKE_DURATION", "20")),
    }


class LogGenerator:
    def __init__(self, cfg, rng=None):
        self.cfg = cfg
        self.rng = rng if rng is not None else random.Random()
        self.path = cfg["log_path"]
        self.spike_error_rate = 0.0
        self.spike_active = False
        self.spike_end = 0.0
        self.next_spike_at = time.monotonic() + self.rng.uniform(
            cfg["spike_min_interval"], cfg["spike_max_interval"]
        )
        self._ensure_file()

    def _ensure_file(self):
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "a", encoding="utf-8"):
            pass

    def rotate_if_needed(self):
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return
        if size > MAX_FILE_BYTES:
            with open(self.path, "w", encoding="utf-8"):
                pass

    def write_line(self, line):
        self.rotate_if_needed()
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()

    def make_line(self, level):
        service = self.rng.choice(SERVICES)
        message = self.rng.choice(MESSAGE_POOLS[level])
        return f"{format_ts(datetime.now(timezone.utc))} {level} {service} {message}"

    def current_error_rate(self):
        return self.spike_error_rate if self.spike_active else NORMAL_ERROR_RATE

    def start_spike(self, now=None):
        if now is None:
            now = time.monotonic()
        self.spike_active = True
        self.spike_error_rate = self.rng.uniform(SPIKE_ERROR_MIN, SPIKE_ERROR_MAX)
        self.spike_end = now + self.cfg["spike_duration"]
        self.next_spike_at = self.spike_end + self.rng.uniform(
            self.cfg["spike_min_interval"], self.cfg["spike_max_interval"]
        )
        ts = format_ts(datetime.now(timezone.utc))
        pct = self.spike_error_rate * 100
        dur = self.cfg["spike_duration"]
        print(f"[spike] started at {ts} error_rate={pct:.0f}% duration={dur:.0f}s", flush=True)

    def end_spike(self):
        self.spike_active = False
        print(f"[spike] ended at {format_ts(datetime.now(timezone.utc))}", flush=True)

    def maybe_spike(self, now=None):
        if now is None:
            now = time.monotonic()
        if self.spike_active:
            if now >= self.spike_end:
                self.end_spike()
        elif now >= self.next_spike_at:
            self.start_spike(now)

    def run_once(self):
        level = pick_level(self.rng, self.current_error_rate())
        self.write_line(self.make_line(level))

    def run(self, stop):
        interval = 1.0 / self.cfg["lines_per_sec"]
        while not stop.is_set():
            self.maybe_spike()
            self.run_once()
            remaining = interval
            while remaining > 0.0 and not stop.is_set():
                chunk = min(remaining, 1.0)
                stop.wait(chunk)
                remaining -= chunk


def main():
    cfg = load_config()
    if cfg["lines_per_sec"] <= 0:
        print("LINES_PER_SEC must be > 0", flush=True)
        return 1
    if cfg["spike_min_interval"] > cfg["spike_max_interval"]:
        print("SPIKE_MIN_INTERVAL must be <= SPIKE_MAX_INTERVAL", flush=True)
        return 1
    stop = threading.Event()

    def handle_signal(signum, frame):
        stop.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    print(
        f"[log-generator] writing to {cfg['log_path']} at {cfg['lines_per_sec']:.1f} lines/sec",
        flush=True,
    )
    gen = LogGenerator(cfg)
    gen.run(stop)
    print("[log-generator] stopped cleanly", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())