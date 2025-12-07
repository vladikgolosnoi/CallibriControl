"""Лёгкий HUD-оверлей поверх всех окон: текущий жест, сила мышцы, усталость."""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets

from callibri_control.ui.widgets import MuscleBar, GestureIndicator, FatigueGauge


class HudOverlay(QtWidgets.QWidget):
    """Прозрачный always-on-top слой с минималистичными индикаторами."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent, QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlag(QtCore.Qt.WindowType.Tool, True)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowDoesNotAcceptFocus, True)
        self.setWindowTitle("Callibri HUD")

        self.muscle = MuscleBar()
        self.gesture = GestureIndicator()
        self.fatigue = FatigueGauge()

        container = QtWidgets.QFrame()
        container.setObjectName("Card")
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        layout.addWidget(self.gesture, 2)
        layout.addWidget(QtWidgets.QLabel("Сила мышцы"))
        layout.addWidget(self.muscle)
        layout.addWidget(QtWidgets.QLabel("Усталость"))
        layout.addWidget(self.fatigue)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(container)

        self.resize(320, 460)
        self.move(60, 60)

    def update_muscle(self, value: float) -> None:
        self.muscle.set_value(value)

    def update_gesture(self, name: str, confidence: float = 0.0) -> None:
        self.gesture.set_gesture(name, confidence)

    def update_fatigue(self, value: int) -> None:
        self.fatigue.set_value(value)
