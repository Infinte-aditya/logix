"""Pure sliding-window statistics. No I/O: timestamps are epoch seconds."""

from collections import deque


class SlidingWindow:
    """Deque of (timestamp, is_error) events, evicted by timestamp."""

    def __init__(self, window_seconds, min_events=20):
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        if min_events < 1:
            raise ValueError("min_events must be >= 1")
        self.window_seconds = window_seconds
        self.min_events = min_events
        self.events = deque()

    def add(self, timestamp, is_error):
        self.events.append((timestamp, is_error))
        self.evict(timestamp)

    def evict(self, now):
        horizon = now - self.window_seconds
        while self.events and self.events[0][0] < horizon:
            self.events.popleft()

    def error_rate(self):
        """Fraction of ERROR events, or None while under min_events."""
        total = len(self.events)
        if total < self.min_events:
            return None
        errors = sum(1 for _, is_error in self.events if is_error)
        return errors / total

    def __len__(self):
        return len(self.events)
