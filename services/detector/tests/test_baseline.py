import pytest
from app.baseline import Baseline


def test_first_update_seeds_mean_with_zero_variance():
    baseline = Baseline(alpha=0.05)
    assert not baseline.ready
    baseline.update(0.02)
    assert baseline.ready
    assert baseline.mean == 0.02
    assert baseline.std == 0.0


def test_mean_converges_and_tracks_spread():
    baseline = Baseline(alpha=0.5)
    for rate in (0.02, 0.04, 0.02, 0.04):
        baseline.update(rate)
    assert 0.02 < baseline.mean < 0.04
    assert baseline.std > 0.0


def test_variance_ignores_negative_rounding():
    baseline = Baseline(alpha=0.05)
    baseline.update(0.02)
    baseline._var = -1e-18  # float noise guard
    assert baseline.std == 0.0


def test_invalid_alpha_rejected():
    with pytest.raises(ValueError):
        Baseline(alpha=0.0)
    with pytest.raises(ValueError):
        Baseline(alpha=1.0)
