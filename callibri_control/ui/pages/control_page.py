"""Страница детального контроля: графики, список жестов, настройки профиля."""

from __future__ import annotations

import random
from typing import Optional

from PyQt6 import QtCore, QtWidgets

from callibri_control.ui.widgets import GestureIndicator, MuscleBar, SignalPlot


class ControlPage(QtWidgets.QWidget):
    """Мониторинг сигналов и управление привязками."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._demo_timer = QtCore.QTimer(self)
        self._demo_timer.timeout.connect(self._tick_demo)
        self._demo_timer.start(70)
        self._demo_enabled = True
        self._build_layout()

    def _build_layout(self) -> None:
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Левая колонка — графики
        left = QtWidgets.QFrame()
        left.setObjectName("Card")
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(10)
        left_layout.addWidget(QtWidgets.QLabel("EMG сигнал"))
        self.emg_plot = SignalPlot(demo_mode=True)
        self.emg_plot.set_thresholds(0.3, 0.6, 0.9)
        left_layout.addWidget(self.emg_plot, 2)

        left_layout.addWidget(QtWidgets.QLabel("Углы наклона"))
        self.tilt_plot = SignalPlot(demo_mode=True)
        left_layout.addWidget(self.tilt_plot, 1)
        layout.addWidget(left, 2)

        # Центральная колонка — жесты
        center = QtWidgets.QFrame()
        center.setObjectName("Card")
        center_layout = QtWidgets.QVBoxLayout(center)
        center_layout.setContentsMargins(12, 12, 12, 12)
        center_layout.setSpacing(8)

        self.gesture_indicator = GestureIndicator()
        center_layout.addWidget(self.gesture_indicator)

        center_layout.addWidget(QtWidgets.QLabel("Последние жесты"))
        self.gesture_list = QtWidgets.QListWidget()
        self.gesture_list.setObjectName("List")
        center_layout.addWidget(self.gesture_list, 1)
        layout.addWidget(center, 2)

        # Правая колонка — профили и пороги
        right = QtWidgets.QFrame()
        right.setObjectName("Card")
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(10)

        right_layout.addWidget(QtWidgets.QLabel("Активный профиль"))
        self.profile_combo = QtWidgets.QComboBox()
        self.profile_combo.addItems(["DEFAULT", "GAMING_WASD", "MEDIA", "MOUSE_CONTROL", "PRESENTATION", "BROWSER", "ACCESSIBILITY"])
        right_layout.addWidget(self.profile_combo)

        right_layout.addWidget(QtWidgets.QLabel("Пороги срабатывания"))
        self.muscle_bar = MuscleBar()
        right_layout.addWidget(self.muscle_bar)

        right_layout.addWidget(QtWidgets.QLabel("Настройка порогов"))
        self.threshold_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.threshold_slider.setRange(10, 90)
        self.threshold_slider.setValue(40)
        right_layout.addWidget(self.threshold_slider)

        self.pause_button = QtWidgets.QPushButton("Пауза распознавания")
        self.pause_button.setObjectName("GhostButton")
        right_layout.addWidget(self.pause_button)
        right_layout.addStretch()
        layout.addWidget(right, 1)

    # Updates -------------------------------------------------------------
    def add_gesture_event(self, gesture: str, confidence: float) -> None:
        self.gesture_indicator.set_gesture(gesture, confidence)
        self.gesture_list.insertItem(0, f"{gesture} • {confidence*100:.0f}%")
        if self.gesture_list.count() > 30:
            self.gesture_list.takeItem(self.gesture_list.count() - 1)

    def set_profile_options(self, profiles: list[str], active: str) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItems(profiles)
        idx = self.profile_combo.findText(active)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)

    def set_demo(self, enabled: bool) -> None:
        self._demo_enabled = enabled
        if enabled:
            if not self._demo_timer.isActive():
                self._demo_timer.start(70)
        else:
            self._demo_timer.stop()

    # Demo ----------------------------------------------------------------
    def _tick_demo(self) -> None:
        if not self._demo_enabled:
            return
        self.emg_plot.append_point(0.4 + random.uniform(-0.2, 0.4))
        self.tilt_plot.append_point(random.uniform(-1.0, 1.0))
        self.muscle_bar.set_value(random.uniform(0.2, 0.9))
        if random.random() > 0.92:
            gesture = random.choice(["MUSCLE_FLEX", "DOUBLE_FLEX", "TILT_LEFT", "TILT_UP"])
            conf = random.uniform(0.6, 0.95)
            self.add_gesture_event(gesture, conf)
