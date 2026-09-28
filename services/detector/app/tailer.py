"""File tailer: like tail -f. Tolerates a missing file, truncation and rotation.

Yields lists of complete lines (possibly empty) on every wake-up so the
caller can keep ticking its detection loop.
"""

import os
import time
from datetime import datetime, timezone

TS_FORMATS = ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ")


def parse_line(line):
    """`<ISO8601 UTC> <LEVEL> <service> <message>` -> (epoch, is_error) or None."""
    parts = line.strip().split(" ", 2)
    if len(parts) < 2:
        return None
    for fmt in TS_FORMATS:
        try:
            stamp = datetime.strptime(parts[0], fmt).replace(tzinfo=timezone.utc)
            return stamp.timestamp(), parts[1] == "ERROR"
        except ValueError:
            continue
    return None


class Tailer:
    def __init__(self, path, poll_seconds=0.2):
        self.path = path
        self.poll_seconds = poll_seconds
        self._fh = None
        self._inode = None
        self._buf = ""

    def _open(self, seek_end):
        try:
            st = os.stat(self.path)
        except OSError:
            return False
        try:
            # Long-lived handle intentionally outlives this call (tail -f); closed in _close().
            self._fh = open(self.path, "r", encoding="utf-8", errors="replace")  # noqa: SIM115
        except OSError:
            return False
        self._inode = st.st_ino
        self._fh.seek(st.st_size if seek_end else 0)
        return True

    def _close(self):
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        self._buf = ""

    def follow(self, stop, sleep=time.sleep):
        """Yield lists of complete new lines, one list per poll."""
        seek_end = True  # start at the end of an existing file...
        while not stop.is_set():
            if self._fh is None:
                if not self._open(seek_end=seek_end):
                    seek_end = False  # ...but read a file created later from the start
                    yield []
                    sleep(self.poll_seconds)
                    continue
                seek_end = False
            try:
                st = os.stat(self.path)
            except OSError:
                self._close()
                continue
            if st.st_ino != self._inode:
                self._close()
                if not self._open(seek_end=False):
                    yield []
                    sleep(self.poll_seconds)
                continue
            if st.st_size < self._fh.tell():
                self._fh.seek(0)
            data = self._fh.read()
            lines = (self._buf + data).split("\n")
            self._buf = lines.pop()
            yield lines
            if not data:
                sleep(self.poll_seconds)
