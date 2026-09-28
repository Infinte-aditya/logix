from app.window import SlidingWindow


def test_evicts_events_older_than_window():
    window = SlidingWindow(60.0, min_events=1)
    for i in range(10):
        window.add(float(i), i % 2 == 0)
    window.evict(90.0)
    assert list(window.events) == []


def test_keeps_recent_events_and_computes_rate():
    window = SlidingWindow(60.0, min_events=1)
    for i in range(100):
        window.add(float(i), i % 50 == 0)  # errors at t=0 and t=50
    window.evict(100.0)
    remaining = list(window.events)
    assert all(ts >= 40.0 for ts, _ in remaining)
    assert len(remaining) == 60
    assert window.error_rate() == 1 / 60  # only the t=50 error survives


def test_evicts_on_add():
    window = SlidingWindow(10.0, min_events=1)
    window.add(0.0, True)
    window.add(100.0, False)
    assert list(window.events) == [(100.0, False)]


def test_rate_none_below_min_events():
    window = SlidingWindow(60.0, min_events=20)
    for i in range(19):
        window.add(float(i), True)
    assert window.error_rate() is None
    window.add(19.0, False)
    assert window.error_rate() == 19 / 20


def test_empty_window_rate_is_zero_when_enough_min_events_configured_low():
    window = SlidingWindow(60.0, min_events=1)
    assert window.error_rate() is None
