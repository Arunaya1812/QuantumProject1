"""
adaptive_threshold.py
------------------------
Implements the "adaptive threshold" idea in a simple, explainable way
(this is the core novel piece of the project, separate from the ML
classifier -- the two can be compared side by side or combined).

HOW IT WORKS (plain terms):
1. CALIBRATION: for the first `calibration_windows` samples, just record
   the QBER values. Compute a baseline mean and standard deviation from
   them. This assumes the channel starts out attack-free (a normal
   real-world assumption -- you calibrate a new link before trusting it).

2. THRESHOLD: the flagging threshold is set at
       threshold = baseline_mean + k * baseline_std
   (k is typically 3, like a statistical control chart / Shewhart chart).

3. ADAPTATION: after calibration, for every new QBER sample:
       - If it's BELOW the current threshold (looks normal), update the
         baseline mean/std using an Exponential Moving Average (EMA).
         This lets the baseline slowly track real environmental drift
         (e.g. fiber aging, temperature changes) without needing a human
         to manually recalibrate.
       - If it's ABOVE the current threshold (looks anomalous), flag it
         as a possible attack and DO NOT update the baseline with it.
         This is important: if we let attack data poison the baseline,
         Eve could slowly "boil the frog" and raise the threshold until
         her attack looks normal. Only trusted (normal-looking) data
         is allowed to shift the baseline.

This is intentionally simple (no deep learning) so it's easy to explain
and defend, and it directly addresses the "noise vs eavesdropper" question
from earlier: gradual drift updates the baseline (no false alarm), while
a sudden/sustained jump gets flagged (real alarm).
"""


class AdaptiveThresholdDetector:
    def __init__(self, calibration_windows: int = 10, k: float = 3.0, ema_alpha: float = 0.1):
        """
        calibration_windows: number of initial samples used to build the
                              first baseline (assumed attack-free)
        k:                    number of standard deviations above the mean
                              that counts as anomalous (higher = less
                              sensitive, fewer false alarms but slower
                              to catch subtle attacks)
        ema_alpha:            smoothing factor for baseline updates on
                              normal-looking data (0 < alpha <= 1).
                              Higher = baseline adapts faster to drift.
        """
        self.calibration_windows = calibration_windows
        self.k = k
        self.ema_alpha = ema_alpha

        self._calib_buffer = []
        self._baseline_mean = None
        self._baseline_std = None
        self._min_std = None  # floor, prevents threshold "collapse" (see note below)
        self.calibrated = False

        # history, useful for plotting / debugging
        self.history = []  # list of dicts: {value, threshold, flagged}

    def _finish_calibration(self):
        import statistics
        self._baseline_mean = statistics.mean(self._calib_buffer)
        self._baseline_std = statistics.pstdev(self._calib_buffer) or 1e-4
        # NOTE ON THE STD FLOOR:
        # We only feed "normal-looking" (non-flagged) values back into the
        # EMA update. That's a truncated sample -- by construction it
        # excludes the larger deviations, which biases the running std
        # estimate DOWNWARD over time. Left unchecked, the threshold slowly
        # tightens on its own even with zero drift, causing more false
        # alarms the longer the system runs (a self-reinforcing collapse).
        # We prevent this by never letting the adaptive std fall below the
        # std measured during calibration -- the baseline is still free to
        # widen (to track real drift/noise increase) but not artificially
        # narrow below what we actually observed.
        self._min_std = self._baseline_std
        self.calibrated = True

    @property
    def threshold(self):
        if not self.calibrated:
            return None
        return self._baseline_mean + self.k * self._baseline_std

    def update(self, value: float, allow_adaptation: bool = True) -> bool:
        """
        Feed in a new QBER (or other) measurement.
        Returns True if this measurement was flagged as anomalous.
        """
        if not self.calibrated:
            self._calib_buffer.append(value)
            if len(self._calib_buffer) >= self.calibration_windows:
                self._finish_calibration()
            self.history.append({"value": value, "threshold": None, "flagged": False})
            return False

        current_threshold = self.threshold
        flagged = value > current_threshold

        if not flagged and allow_adaptation:
            # Trusted, normal-looking data -> slowly adapt the baseline
            self._baseline_mean = (
                (1 - self.ema_alpha) * self._baseline_mean + self.ema_alpha * value
            )
            deviation = abs(value - self._baseline_mean)
            self._baseline_std = (
                (1 - self.ema_alpha) * self._baseline_std + self.ema_alpha * deviation
            )
            self._baseline_std = max(self._baseline_std, self._min_std)

        self.history.append({
            "value": value,
            "threshold": current_threshold,
            "flagged": flagged,
            "adapted": bool(not flagged and allow_adaptation),
        })
        return flagged


class StaticThresholdDetector:
    """
    A simple, non-adaptive baseline for comparison: a single fixed
    threshold for the entire timeline, set once from calibration data
    and never updated. This represents the "old way" (naive fixed
    threshold) that the adaptive detector is meant to improve on.
    """

    def __init__(self, calibration_windows: int = 10, k: float = 3.0):
        self.calibration_windows = calibration_windows
        self.k = k
        self._calib_buffer = []
        self._fixed_threshold = None
        self.calibrated = False
        self.history = []

    def update(self, value: float) -> bool:
        import statistics

        if not self.calibrated:
            self._calib_buffer.append(value)
            if len(self._calib_buffer) >= self.calibration_windows:
                mean = statistics.mean(self._calib_buffer)
                std = statistics.pstdev(self._calib_buffer) or 1e-4
                self._fixed_threshold = mean + self.k * std
                self.calibrated = True
            self.history.append({"value": value, "threshold": None, "flagged": False})
            return False

        flagged = value > self._fixed_threshold
        self.history.append({
            "value": value,
            "threshold": self._fixed_threshold,
            "flagged": flagged,
        })
        return flagged
