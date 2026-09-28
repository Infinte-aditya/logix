import os
from datetime import datetime, timezone

import pytest

from app.tailer import Tailer, parse_line


def test_parse_line_accepts_contract_format():
    expected = datetime(2026, 9, 28, 12, 0, 0, 123000, tzinfo=timezone.utc).timestamp()
    assert parse_line("2026-09-28T12:00:00.123Z ERROR auth db down") == (expected, True)
    assert parse_line("2026-09-28T12:00:00Z INFO auth ok")[1] is False
    assert parse_line("2026-09-28T12:00:00.123Z WARN auth slow")[1] is False


def test_parse_line_rejects_garbage():
    assert parse_line("not a log line") is None
    assert parse_line("") is None
    assert parse_line("99/99/99 ERROR auth x") is None


def test_starts_at_end_and_reads_appends(tmp_path, stop, noop_sleep):
    path = tmp_path / "app.log"
    path.write_text("old line\n")
    gen = Tailer(str(path)).follow(stop, sleep=noop_sleep)
    assert next(gen) == []
    with path.open("a", encoding="utf-8") as f:
        f.write("new-1\nnew-2\n")
    assert next(gen) == ["new-1", "new-2"]
    assert next(gen) == []


def test_waits_for_missing_file(tmp_path, stop, noop_sleep):
    path = tmp_path / "app.log"
    gen = Tailer(str(path)).follow(stop, sleep=noop_sleep)
    assert next(gen) == []
    path.write_text("late line\n")
    assert next(gen) == ["late line"]


def test_follows_truncation(tmp_path, stop, noop_sleep):
    path = tmp_path / "app.log"
    path.write_text("first\n")
    gen = Tailer(str(path)).follow(stop, sleep=noop_sleep)
    assert next(gen) == []
    path.write_text("")  # truncate in place
    assert next(gen) == []  # poll observes truncation and rewinds
    with path.open("a", encoding="utf-8") as f:
        f.write("after truncate\n")
    assert next(gen) == ["after truncate"]


def test_follows_rotation(tmp_path, stop, noop_sleep):
    path = tmp_path / "app.log"
    path.write_text("before rotation\n")
    gen = Tailer(str(path)).follow(stop, sleep=noop_sleep)
    assert next(gen) == []
    rotated = tmp_path / "app.log.1"
    os.replace(path, rotated)  # simulate logrotate
    path.write_text("after rotation\n")
    assert next(gen) == ["after rotation"]


def test_keeps_partial_line_in_buffer(tmp_path, stop, noop_sleep):
    path = tmp_path / "app.log"
    path.write_text("old\n")
    gen = Tailer(str(path)).follow(stop, sleep=noop_sleep)
    assert next(gen) == []
    with path.open("a", encoding="utf-8") as f:
        f.write("partial")
    assert next(gen) == []
    with path.open("a", encoding="utf-8") as f:
        f.write(" rest\nnext\n")
    assert next(gen) == ["partial rest", "next"]


def test_stop_event_ends_iteration(tmp_path, stop, noop_sleep):
    path = tmp_path / "app.log"
    path.write_text("x\n")
    gen = Tailer(str(path)).follow(stop, sleep=noop_sleep)
    next(gen)
    stop.set()
    with pytest.raises(StopIteration):
        next(gen)
