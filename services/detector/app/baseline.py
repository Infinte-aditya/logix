"""Pure exponentially weighted baseline of the window error rate.

Callers MUST NOT update() while an anomaly is active, or spikes poison
the baseline (the pipeline in main.py enforces this).
"""


class Baseline:
    """EW mean and variance of the error rate."""

    def __init__(self, alpha=0.05):
        if not 0 < alpha < 1:
            raise ValueError("alpha must be in (0, 1)")
        self.alpha = alpha
        self.mean = None
        self._var = None

    @property
    def ready(self):
        return self.mean is not None

    @property
    def std(self):
        if self._var is None:
            return 0.0
        return max(self._var, 0.0) ** 0.5

    def update(self, rate):
        """Fold one observed rate into the mean and variance."""
        if self.mean is None:
            self.mean = rate
            self._var = 0.0
            return
        delta = rate - self.mean
        self.mean += self.alpha * delta
        self._var += self.alpha * (delta * delta - self._var)

    def prime(self, mean, std=0.0):
        """Seed the baseline at a known normal rate (skips EWMA warm-up drift)."""
        self.mean = mean
        self._var = std * std
