"""Muscle fatigue monitor using EMG trends."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional

import numpy as np
from scipy import signal


@dataclass
class FatigueState:
    index: float
    trend: str
    median_freq: float
    mean_freq: float
    rms: float


class FatigueMonitor:
    """
    Отслеживает усталость по тренду RMS и спектральным метрикам (median/mean frequency).
    Использует скользящее окно последних N секунд EMG.
    """

    def __init__(self, fs: int = 500, window_sec: float = 4.0) -> None:
        self.fs = fs
        self.window_sec = window_sec
        self.buffer: Deque[float] = deque(maxlen=int(fs * window_sec))
        self.baseline_median: Optional[float] = None
        self.baseline_mean: Optional[float] = None
        self.baseline_rms: Optional[float] = None
        self._last_index = 0.0
        self._last_time = time.time()

    def update(self, samples) -> Optional[FatigueState]:
        """Принимает numpy/iterable EMG сегмента, возвращает состояние или None, если мало данных."""
        self.buffer.extend(samples)
        if len(self.buffer) < self.buffer.maxlen // 2:
            return None

        data = np.asarray(self.buffer, dtype=float)
        rms = float(np.sqrt(np.mean(data**2)))

        freqs, psd = signal.welch(data, fs=self.fs, nperseg=min(512, len(data)))
        cumsum = np.cumsum(psd)
        total = cumsum[-1] if cumsum.size else 0.0
        if total <= 0:
            return None
        median_freq = float(freqs[np.searchsorted(cumsum, total * 0.5)])
        mean_freq = float(np.sum(freqs * psd) / total)

        if self.baseline_median is None:
            self.baseline_median = median_freq
            self.baseline_mean = mean_freq
            self.baseline_rms = rms
            return None

        # Индекс усталости: падение median/mean частоты + рост RMS
        median_drop = (self.baseline_median - median_freq) / max(self.baseline_median, 1e-6)
        mean_drop = (self.baseline_mean - mean_freq) / max(self.baseline_mean, 1e-6)
        rms_growth = (rms - self.baseline_rms) / max(self.baseline_rms, 1e-6)
        index = max(0.0, median_drop * 0.45 + mean_drop * 0.35 + rms_growth * 0.2)

        trend = self._trend(index)
        self._last_index = index
        return FatigueState(index=index, trend=trend, median_freq=median_freq, mean_freq=mean_freq, rms=rms)

    def _trend(self, current: float) -> str:
        now = time.time()
        dt = max(now - self._last_time, 1e-3)
        delta = current - self._last_index
        self._last_time = now
        if delta > 0.02:
            return "rising"
        if delta < -0.02:
            return "recovering"
        return "stable"
