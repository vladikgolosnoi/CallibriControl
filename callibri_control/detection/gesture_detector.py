"""Gesture detector based on EMG RMS and MEMS angles/acceleration."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from callibri_control.detection.adaptive_thresholds import AdaptiveThresholds, Thresholds
from callibri_control.detection.fatigue_monitor import FatigueMonitor, FatigueState


GestureEvent = Dict[str, object]


@dataclass
class DetectorConfig:
    profile: str = "NORMAL"
    emg_hold_ms: int = 400
    emg_pulse_max_ms: int = 250
    emg_gap_ms: int = 400
    double_window_ms: int = 500
    triple_window_ms: int = 800
    tilt_deg: float = 25.0
    tilt_hold_ms: int = 120       # удержание наклона перед срабатыванием
    tilt_cooldown_ms: int = 700   # пауза между срабатываниями одного направления
    shake_g: float = 2.0
    punch_g: float = 1.6


class GestureDetector:
    """
    Детектор простых EMG и MEMS жестов:
    - EMG: FLEX (импульс), HOLD, RELEASE, DOUBLE_FLEX, TRIPLE_FLEX, GRADUAL_UP/DOWN
    - MEMS: TILT_{UP,DOWN,LEFT,RIGHT}, SHAKE, PUNCH
    - Комбо: FLEX+TILT_{UP/DOWN}
    """

    def __init__(self, thresholds: AdaptiveThresholds, fatigue: Optional[FatigueMonitor] = None, config: Optional[DetectorConfig] = None) -> None:
        self.config = config or DetectorConfig()
        self.thresholds_mgr = thresholds
        self.fatigue = fatigue
        self._last_emg_state = "idle"
        self._last_emg_change = time.time()
        self._last_flex_ts: List[float] = []
        self._last_gesture_ts: Dict[str, float] = {}
        self._fatigue_state: Optional[FatigueState] = None
        self._last_rms = 0.0
        # Для стабильных MEMS-жестов: отслеживание начала превышения
        self._tilt_start_ts: Dict[str, float] = {}

    # ------------------------------------------------------------------ Public API
    def process_metrics(self, metrics: Dict[str, float]) -> List[GestureEvent]:
        """
        Принимает словарь метрик (из DataStream.latest_metrics()).
        Возвращает список жестов, возникших на этом шаге.
        """
        events: List[GestureEvent] = []
        now = time.time()

        rms = float(metrics.get("emg_rms", 0.0))
        self._last_rms = rms
        pitch = float(metrics.get("pitch", 0.0))
        roll = float(metrics.get("roll", 0.0))
        acc_mag = float(metrics.get("acc_magnitude", 1.0))

        # Усталость -> корректируем пороги
        if self.fatigue is not None:
            fs_guess = 500
            fatigue_state = self.fatigue.update([rms])
            if fatigue_state:
                self._fatigue_state = fatigue_state
                fatigue_factor = max(0.6, 1.0 - fatigue_state.index * 0.5)
                self.thresholds_mgr.apply_fatigue(fatigue_factor)

        # EMG жесты
        events.extend(self._detect_emg(now, rms))
        # MEMS жесты
        events.extend(self._detect_mems(now, pitch, roll, acc_mag))
        return events

    def fatigue_state(self) -> Optional[FatigueState]:
        return self._fatigue_state

    # ------------------------------------------------------------------ Internal EMG
    def _detect_emg(self, now: float, rms: float) -> List[GestureEvent]:
        events: List[GestureEvent] = []
        th: Thresholds = self.thresholds_mgr.thresholds_for_profile(self.config.profile)
        state = self._last_emg_state

        above_on = rms >= th.on
        below_off = rms <= th.off
        elapsed = (now - self._last_emg_change) * 1000

        if state == "idle" and above_on:
            state = "active"
            self._last_emg_change = now
            events.append(self._event("MUSCLE_FLEX", rms, duration_ms=0))
            self._register_flex(now, events, rms)

        elif state == "active":
            if below_off and elapsed >= th.debounce_ms:
                state = "idle"
                self._last_emg_change = now
                events.append(self._event("MUSCLE_RELEASE", rms, duration_ms=int(elapsed)))
            elif elapsed >= self.config.emg_hold_ms:
                state = "holding"
                self._last_emg_change = now
                events.append(self._event("MUSCLE_HOLD", rms, duration_ms=int(elapsed)))

        elif state == "holding":
            if below_off and elapsed >= th.debounce_ms:
                state = "idle"
                self._last_emg_change = now
                events.append(self._event("MUSCLE_RELEASE", rms, duration_ms=int(elapsed)))

        # Градиентные жесты (по скорости изменения RMS)
        if elapsed > 50:
            events.extend(self._detect_gradual(now, rms))

        self._last_emg_state = state
        return events

    def _register_flex(self, now: float, events: List[GestureEvent], rms: float) -> None:
        self._last_flex_ts.append(now)
        self._last_flex_ts = [t for t in self._last_flex_ts if now - t <= self.config.triple_window_ms / 1000]
        if len(self._last_flex_ts) >= 3:
            events.append(self._event("TRIPLE_FLEX", rms))
            self._last_flex_ts.clear()
        elif len(self._last_flex_ts) == 2 and (self._last_flex_ts[-1] - self._last_flex_ts[-2]) * 1000 <= self.config.double_window_ms:
            events.append(self._event("DOUBLE_FLEX", rms))

    def _detect_gradual(self, now: float, rms: float) -> List[GestureEvent]:
        events: List[GestureEvent] = []
        delta = rms - self._last_rms
        # Простой порог на изменение
        if delta > 0.05 * max(rms, 1e-3):
            events.append(self._event("GRADUAL_INCREASE", rms))
        elif delta < -0.05 * max(self._last_rms, 1e-3):
            events.append(self._event("GRADUAL_DECREASE", rms))
        return events

    # ------------------------------------------------------------------ MEMS
    def _detect_mems(self, now: float, pitch: float, roll: float, acc_mag: float) -> List[GestureEvent]:
        events: List[GestureEvent] = []
        tilt = self.config.tilt_deg
        hold_ms = self.config.tilt_hold_ms
        cooldown_ms = self.config.tilt_cooldown_ms

        def _maybe_tilt(name: str, value: float) -> None:
            if abs(value) < tilt:
                self._tilt_start_ts.pop(name, None)
                return
            start = self._tilt_start_ts.get(name)
            if start is None:
                self._tilt_start_ts[name] = now
                return
            if (now - start) * 1000 < hold_ms:
                return
            if self._debounce(name, now, cooldown_ms):
                events.append(self._event(name, value))
                self._tilt_start_ts[name] = now

        if pitch > tilt:
            _maybe_tilt("TILT_UP", pitch)
        elif pitch < -tilt:
            _maybe_tilt("TILT_DOWN", pitch)
        else:
            self._tilt_start_ts.pop("TILT_UP", None)
            self._tilt_start_ts.pop("TILT_DOWN", None)

        if roll > tilt:
            _maybe_tilt("TILT_RIGHT", roll)
        elif roll < -tilt:
            _maybe_tilt("TILT_LEFT", roll)
        else:
            self._tilt_start_ts.pop("TILT_RIGHT", None)
            self._tilt_start_ts.pop("TILT_LEFT", None)

        # Shake / Punch
        if acc_mag > self.config.shake_g and self._debounce("SHAKE", now, 600):
            events.append(self._event("SHAKE", acc_mag))
            self._last_gesture_ts["SHAKE"] = now
        if acc_mag > self.config.punch_g and self._debounce("PUNCH", now, 400):
            events.append(self._event("PUNCH", acc_mag))
            self._last_gesture_ts["PUNCH"] = now

        # Комбо: если свежий FLEX (<0.5s) и tilt_up/down/left/right
        recent_flex = any(now - t < 0.5 for t in self._last_flex_ts)
        if recent_flex:
            if pitch > tilt and self._debounce("FLEX_TILT_UP", now, 300):
                events.append(self._event("FLEX_TILT_UP", pitch))
            elif pitch < -tilt and self._debounce("FLEX_TILT_DOWN", now, 300):
                events.append(self._event("FLEX_TILT_DOWN", pitch))
            if roll > tilt and self._debounce("FLEX_TILT_RIGHT", now, 300):
                events.append(self._event("FLEX_TILT_RIGHT", roll))
            elif roll < -tilt and self._debounce("FLEX_TILT_LEFT", now, 300):
                events.append(self._event("FLEX_TILT_LEFT", roll))

        return events

    # ------------------------------------------------------------------ Helpers
    def _event(self, name: str, value: float, duration_ms: int = 0) -> GestureEvent:
        return {
            "type": name,
            "value": value,
            "duration_ms": duration_ms,
            "timestamp": time.time(),
        }

    def _debounce(self, name: str, now: float, window_ms: int) -> bool:
        last = self._last_gesture_ts.get(name, 0.0)
        if (now - last) * 1000 < window_ms:
            return False
        self._last_gesture_ts[name] = now
        return True
