"""Adaptive thresholds based on calibration and fatigue."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


SENSITIVITY_PROFILES: Dict[str, Dict[str, float]] = {
    # Пониженные пороги для слабых сокращений (on/off — доля от диапазона MVC-baseline)
    "ULTRA_SENSITIVE": {"on": 0.008, "off": 0.004, "debounce_ms": 150},
    "SENSITIVE": {"on": 0.08, "off": 0.05, "debounce_ms": 200},
    "NORMAL": {"on": 0.24, "off": 0.14, "debounce_ms": 220},
    "GAMING": {"on": 0.18, "off": 0.12, "debounce_ms": 180},
    "PRECISE": {"on": 0.38, "off": 0.26, "debounce_ms": 280},
}


@dataclass
class Thresholds:
    on: float
    off: float
    debounce_ms: int


class AdaptiveThresholds:
    """
    Рассчитывает пороги активации/деактивации EMG с учётом персональной калибровки и усталости.
    """

    def __init__(self, mvc: float = 1.0, baseline: float = 0.0) -> None:
        self.mvc = max(mvc, 1e-6)
        self.baseline = baseline
        self.fatigue_factor = 1.0  # 1.0 без коррекции, <1 снижает пороги

    def update_calibration(self, mvc: float, baseline: float) -> None:
        self.mvc = max(mvc, 1e-6)
        self.baseline = baseline

    def apply_fatigue(self, factor: float) -> None:
        """
        Учитывает усталость: factor < 1.0 снижает пороги, >1.0 повышает.
        """
        self.fatigue_factor = max(0.2, min(factor, 2.0))

    def thresholds_for_profile(self, profile: str) -> Thresholds:
        cfg = SENSITIVITY_PROFILES.get(profile.upper(), SENSITIVITY_PROFILES["NORMAL"])
        span = self.mvc - self.baseline
        on = self.baseline + span * cfg["on"] * self.fatigue_factor
        off = self.baseline + span * cfg["off"] * self.fatigue_factor
        return Thresholds(on=on, off=off, debounce_ms=int(cfg["debounce_ms"]))

    def all_profiles(self) -> Dict[str, Thresholds]:
        return {name: self.thresholds_for_profile(name) for name in SENSITIVITY_PROFILES}
