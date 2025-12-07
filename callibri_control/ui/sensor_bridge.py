"""Простой мост: автоподключение к Callibri, DataStream и сигналы для UI."""

from __future__ import annotations

import contextlib
import threading
import time
from typing import Optional, List

import numpy as np

from PyQt6 import QtCore

from callibri_control.core.data_stream import DataStream
from callibri_control.core.sensor_manager import SensorManager
from callibri_control.utils.config_manager import ConfigManager
from callibri_control.detection.adaptive_thresholds import AdaptiveThresholds
from callibri_control.detection.fatigue_monitor import FatigueMonitor
from callibri_control.detection.gesture_detector import GestureDetector, DetectorConfig
from callibri_control.control.profiles import ProfileManager
from callibri_control.control.keyboard_emulator import KeyboardEmulator
from callibri_control.control.mouse_emulator import MouseEmulator


class SensorBridge(QtCore.QObject):
    deviceInfo = QtCore.pyqtSignal(dict)
    statusText = QtCore.pyqtSignal(str, int)  # text, battery
    emgRms = QtCore.pyqtSignal(float)
    orientation = QtCore.pyqtSignal(float, float, float)
    accMagnitude = QtCore.pyqtSignal(float)
    gestureDetected = QtCore.pyqtSignal(dict)
    fatigueIndex = QtCore.pyqtSignal(float)

    def __init__(self, manager: Optional[SensorManager], cfg: Optional[ConfigManager] = None) -> None:
        super().__init__()
        self.manager = manager
        self.cfg = cfg
        self.stream: Optional[DataStream] = None
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.demo_mode = bool(cfg.config.get("general", {}).get("demo_mode", False) if cfg else False)
        self.thresholds = AdaptiveThresholds(mvc=0.2, baseline=0.0)
        self.detector = GestureDetector(
            self.thresholds,
            fatigue=FatigueMonitor(fs=int((cfg.config.get("sensor", {}).get("emg_sampling_rate", 500)) if cfg else 500)),
            config=DetectorConfig(profile=(cfg.config.get("recognition", {}).get("sensitivity_profile", "ULTRA_SENSITIVE") if cfg else "ULTRA_SENSITIVE")),
        )
        self._profile = (cfg.config.get("recognition", {}).get("sensitivity_profile", "ULTRA_SENSITIVE") if cfg else "ULTRA_SENSITIVE")
        profiles_path = getattr(cfg, "profiles_path", None)
        self.profile_mgr = ProfileManager(storage=profiles_path)
        if cfg and cfg.config.get("control", {}).get("profile"):
            self.profile_mgr.set_active(cfg.config["control"]["profile"])
        self.kb = KeyboardEmulator()
        self.mouse = MouseEmulator()

    @QtCore.pyqtSlot()
    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    @QtCore.pyqtSlot()
    def stop(self) -> None:
        self._stop.set()
        if self.stream:
            with contextlib.suppress(Exception):
                self.stream.stop()
        with contextlib.suppress(Exception):
            self.manager.disconnect()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=1.0)

    def _loop(self) -> None:
        if self.demo_mode or self.manager is None:
            self._loop_demo()
            return

        self.statusText.emit("Поиск устройств...", 0)
        devices = self.manager.scan_devices()
        if not devices:
            if self.demo_mode:
                self._loop_demo()
                return
            self.statusText.emit("Нет Callibri рядом", 0)
            return
        target = devices[0]["sensor_info"]
        if not self.manager.connect(target, wait=True, timeout=self.manager.scan_timeout + 5):
            if self.demo_mode:
                self._loop_demo()
                return
            self.statusText.emit("Не удалось подключиться", 0)
            return
        info = self.manager.get_device_info() or {}
        battery = int(info.get("battery", 0) or 0) if str(info.get("battery", "")).isdigit() else 0
        self.deviceInfo.emit(info)
        self.statusText.emit("Активно", battery)

        device = self.manager.get_device()
        if device is None:
            self.statusText.emit("Ошибка устройства", battery)
            return

        use_envelope = bool((self.cfg.config.get("sensor", {}) if self.cfg else {}).get("use_envelope", True))
        self.stream = DataStream(
            device,
            emg_rate=int((self.cfg.config.get("sensor", {}).get("emg_sampling_rate", 500)) if self.cfg else 500),
            use_envelope=use_envelope,
            enable_mems=True,
            enable_orientation=True,
            rms_window_sec=0.12,
        )
        self.stream.start()
        self._auto_calibrate()

        try:
            while not self._stop.is_set():
                metrics = self.stream.latest_metrics()
                rms = float(metrics.get("emg_rms", 0.0) or 0.0)
                # динамическое адаптирование baseline/mvc для живых демонстраций без отдельной калибровки
                if rms < self.thresholds.baseline * 1.2 + 0.01:
                    self.thresholds.baseline = 0.98 * self.thresholds.baseline + 0.02 * rms
                if rms > self.thresholds.mvc * 0.9:
                    self.thresholds.update_calibration(mvc=max(rms, self.thresholds.mvc), baseline=self.thresholds.baseline)

                self.emgRms.emit(rms)
                self.orientation.emit(
                    float(metrics.get("pitch", 0.0) or 0.0),
                    float(metrics.get("roll", 0.0) or 0.0),
                    float(metrics.get("yaw", 0.0) or 0.0),
                )
                self.accMagnitude.emit(float(metrics.get("acc_magnitude", 0.0) or 0.0))

                events = self.detector.process_metrics(metrics)
                fatigue_state = self.detector.fatigue_state()
                if fatigue_state:
                    self.fatigueIndex.emit(float(fatigue_state.index))
                for ev in events:
                    self.gestureDetected.emit(ev)
                    self._execute_action(ev)

                # обновляем батарею из устройства, если доступно
                try:
                    batt_val = getattr(device, "batt_power", None)
                    if batt_val is not None:
                        battery = int(batt_val)
                except Exception:
                    pass
                self.statusText.emit("Активно", battery)
                time.sleep(0.05)
        finally:
            with contextlib.suppress(Exception):
                self.stream.stop()
            with contextlib.suppress(Exception):
                self.manager.disconnect()

    def _loop_demo(self) -> None:
        """Симуляция потока без датчика для демонстраций/тестов."""
        self.statusText.emit("Демо режим", 0)
        # Настройка порогов под синтетический сигнал
        self.thresholds.update_calibration(mvc=0.6, baseline=0.08)
        t = 0.0
        while not self._stop.is_set():
            # EMG: базовый шум + импульсы
            rms = 0.08 + 0.05 * np.sin(t) + np.random.uniform(0, 0.05)
            if np.random.rand() > 0.96:
                rms += 0.35  # всплеск как FLEX

            pitch = 15 * np.sin(t / 1.5)
            roll = 18 * np.sin(t / 1.1 + 1.3)
            acc_mag = 1.0 + abs(np.sin(t)) * 0.6
            metrics = {
                "emg_rms": rms,
                "pitch": pitch,
                "roll": roll,
                "acc_magnitude": acc_mag,
            }
            self.emgRms.emit(rms)
            self.orientation.emit(pitch, roll, 0.0)
            self.accMagnitude.emit(acc_mag)

            events = self.detector.process_metrics(metrics)
            fatigue_state = self.detector.fatigue_state()
            if fatigue_state:
                self.fatigueIndex.emit(float(fatigue_state.index))
            for ev in events:
                self.gestureDetected.emit(ev)
                self._execute_action(ev)

            self.statusText.emit("Демо режим", 100)
            t += 0.08
            time.sleep(0.05)
    def _auto_calibrate(self) -> None:
        """Мини-калибровка: берём окно RMS, вычисляем baseline/peak и обновляем пороги."""
        if not self.stream:
            return
        rms_samples: List[float] = []
        t_end = time.time() + 1.5
        while time.time() < t_end and not self._stop.is_set():
            metrics = self.stream.latest_metrics()
            rms_samples.append(float(metrics.get("emg_rms", 0.0) or 0.0))
            time.sleep(0.05)
        if not rms_samples:
            return
        baseline = float(np.percentile(rms_samples, 20))
        mvc = float(np.percentile(rms_samples, 95))
        mvc = max(mvc, baseline + 0.05)
        self.thresholds.update_calibration(mvc=mvc, baseline=baseline)

    def set_control_profile(self, name: str) -> None:
        try:
            self.profile_mgr.set_active(name)
        except Exception:
            self.profile_mgr.set_active("DEFAULT")

    def _execute_action(self, event: dict) -> None:
        action = self.profile_mgr.get_action(event.get("type", ""))
        if not action:
            return
        try:
            if action.get("type") == "keyboard":
                self.kb.execute(self.profile_mgr.mapper.to_keyboard_action(action))  # type: ignore[arg-type]
            elif action.get("type") == "mouse":
                self.mouse.execute(self.profile_mgr.mapper.to_mouse_action(action))  # type: ignore[arg-type]
            elif action.get("type") == "macro":
                for step in action.get("steps", []):
                    if step.get("type") == "keyboard":
                        self.kb.execute(self.profile_mgr.mapper.to_keyboard_action(step))  # type: ignore[arg-type]
                    elif step.get("type") == "mouse":
                        self.mouse.execute(self.profile_mgr.mapper.to_mouse_action(step))  # type: ignore[arg-type]
                    time.sleep(step.get("delay", 0) / 1000 if isinstance(step, dict) else 0)
        except Exception:
            # не рушим поток стриминга из-за экшена
            pass
