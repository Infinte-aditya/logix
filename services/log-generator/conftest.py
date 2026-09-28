import random

import pytest

from app.main import LogGenerator


@pytest.fixture
def generator(tmp_path):
    return LogGenerator(
        {
            "log_path": str(tmp_path / "app.log"),
            "lines_per_sec": 10.0,
            "spike_min_interval": 60.0,
            "spike_max_interval": 120.0,
            "spike_duration": 20.0,
        },
        rng=random.Random(42),
    )


@pytest.fixture
def read_lines():
    def _read(path):
        with open(path, "r", encoding="utf-8") as f:
            return [line for line in f.read().splitlines() if line]

    return _read


@pytest.fixture
def error_ratio():
    def _ratio(lines):
        errors = sum(1 for line in lines if " ERROR " in line)
        return errors / len(lines)

    return _ratio