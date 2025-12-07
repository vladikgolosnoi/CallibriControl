"""Главная страница (Dashboard): статус устройства и быстрые действия."""

from __future__ import annotations

import random
from typing import Optional

from PyQt6 import QtCore, QtWidgets

from callibri_control.ui.widgets import FatigueGauge, GestureIndicator, MuscleBar, SignalPlot, OrientationVisualizer


class DashboardPage(QtWidgets.QWidget):
    """Каркас главной страницы с визуализацией текущего состояния."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._device_info = {"name": "Не подключено", "serial": "—", "fw": "—", "battery": 0}
        self._state = "Готов"
        self._fatigue = 0
        self._demo_timer = QtCore.QTimer(self)
        self._demo_timer.timeout.connect(self._tick_demo)
        self._demo_enabled = True
        self._demo_timer.start(80)
        self._demo_phase = 0.0

        self._build_layout()

    def _build_layout(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._device_card())

        center = QtWidgets.QHBoxLayout()
        center.setSpacing(12)
        center.addWidget(self._live_panel(), 3)
        center.addWidget(self._metrics_panel(), 2)
        layout.addLayout(center, 1)

        layout.addWidget(self._quick_actions())

    def _device_card(self) -> QtWidgets.QWidget:
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        card_layout = QtWidgets.QGridLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setHorizontalSpacing(20)
        card_layout.setVerticalSpacing(8)

        self.device_name = QtWidgets.QLabel("Callibri — Не подключено")
        self.device_serial = QtWidgets.QLabel("Серийный: —")
        self.device_fw = QtWidgets.QLabel("Прошивка: —")
        self.device_batt = QtWidgets.QLabel("🔋 0%")
        for lbl in (self.device_name, self.device_serial, self.device_fw, self.device_batt):
            lbl.setObjectName("SecondaryText")

        card_layout.addWidget(QtWidgets.QLabel("Устройство"), 0, 0)
        card_layout.addWidget(self.device_name, 1, 0)
        card_layout.addWidget(QtWidgets.QLabel("Состояние"), 0, 1)
        self.state_label = QtWidgets.QLabel("💪 Готов")
        card_layout.addWidget(self.state_label, 1, 1)
        card_layout.addWidget(QtWidgets.QLabel("Версия"), 0, 2)
        card_layout.addWidget(self.device_fw, 1, 2)
        card_layout.addWidget(QtWidgets.QLabel("Батарея"), 0, 3)
        card_layout.addWidget(self.device_batt, 1, 3)

        return card

    def _live_panel(self) -> QtWidgets.QWidget:
        frame = QtWidgets.QFrame()
        frame.setObjectName("Card")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.gesture_indicator = GestureIndicator()
        layout.addWidget(self.gesture_indicator, 3)

        # Небольшой график EMG
        self.emg_plot = SignalPlot(demo_mode=True)
        self.emg_plot.set_thresholds(0.3, 0.6, 0.9)
        layout.addWidget(self.emg_plot, 1)
        return frame

    def _metrics_panel(self) -> QtWidgets.QWidget:
        frame = QtWidgets.QFrame()
        frame.setObjectName("Card")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.muscle_bar = MuscleBar(thresholds=(0.4, 0.7))
        layout.addWidget(QtWidgets.QLabel("Сила мышцы"))
        layout.addWidget(self.muscle_bar)

        self.fatigue = FatigueGauge()
        layout.addWidget(QtWidgets.QLabel("Усталость"))
        layout.addWidget(self.fatigue)

        self.orientation = OrientationVisualizer(demo_mode=True)
        layout.addWidget(QtWidgets.QLabel("Ориентация"))
        layout.addWidget(self.orientation)

        return frame

    def _quick_actions(self) -> QtWidgets.QWidget:
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        layout = QtWidgets.QHBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.start_btn = QtWidgets.QPushButton("Старт")
        self.start_btn.setObjectName("PrimaryButton")
        self.calibrate_btn = QtWidgets.QPushButton("Калибровка")
        self.calibrate_btn.setObjectName("GhostButton")
        self.games_btn = QtWidgets.QPushButton("Игры")
        self.games_btn.setObjectName("GhostButton")
        self.training_btn = QtWidgets.QPushButton("Тренировки")
        self.training_btn.setObjectName("GhostButton")
        self.profiles_btn = QtWidgets.QPushButton("Профили")
        self.profiles_btn.setObjectName("GhostButton")

        for btn in (
            self.start_btn,
            self.calibrate_btn,
            self.games_btn,
            self.training_btn,
            self.profiles_btn,
        ):
            layout.addWidget(btn)
        layout.addStretch()
        return card

    # Updates -------------------------------------------------------------
    def update_device(self, name: str, serial: str, firmware: str, battery: int) -> None:
        self._device_info.update({"name": name, "serial": serial, "fw": firmware, "battery": battery})
        self.device_name.setText(f"{name}")
        self.device_serial.setText(f"Серийный: {serial}")
        self.device_fw.setText(f"Прошивка: {firmware}")
        self.device_batt.setText(f"🔋 {battery}%")

    def update_state(self, state: str) -> None:
        self._state = state
        self.state_label.setText(f"💪 {state}")

    def update_fatigue(self, value: int) -> None:
        self._fatigue = value
        self.fatigue.set_value(value)

    def set_demo(self, enabled: bool) -> None:
        self._demo_enabled = enabled
        if enabled:
            if not self._demo_timer.isActive():
                self._demo_timer.start(80)
            self.orientation.enable_demo(True)
        else:
            self._demo_timer.stop()
            self.orientation.enable_demo(False)

    # Demo ----------------------------------------------------------------
    def _tick_demo(self) -> None:
        if not self._demo_enabled:
            return
        self._demo_phase += 0.12
        muscle_value = 0.35 + 0.4 * max(0, random.random() - 0.4)
        self.muscle_bar.set_value(muscle_value)
        self.fatigue.set_value(int((0.3 + 0.2 * random.random()) * 100))
        if random.random() > 0.9:
            gesture = random.choice(["MUSCLE_FLEX", "TILT_UP", "DOUBLE_FLEX"])
            self.gesture_indicator.set_gesture(gesture, confidence=random.random())
            self.emg_plot.append_point(0.95, event=gesture)
