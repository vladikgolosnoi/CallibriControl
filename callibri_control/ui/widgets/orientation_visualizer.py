"""Визуализация ориентации датчика (упрощённый 3D вид сверху)."""

from __future__ import annotations

import math
import random
from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets


class OrientationVisualizer(QtWidgets.QWidget):
    """Рисует прямоугольник-датчик, поворачивая его по roll/pitch, стрелку yaw."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None, demo_mode: bool = False) -> None:
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.pitch = 0.0
        self.roll = 0.0
        self.yaw = 0.0
        self._demo_mode = demo_mode
        self._demo_timer = QtCore.QTimer(self)
        self._demo_timer.timeout.connect(self._tick_demo)
        if demo_mode:
            self.enable_demo(True)

    def set_orientation(self, pitch: float, roll: float, yaw: float = 0.0) -> None:
        self.pitch = pitch
        self.roll = roll
        self.yaw = yaw
        self.update()

    def enable_demo(self, enabled: bool) -> None:
        self._demo_mode = enabled
        if enabled:
            if not self._demo_timer.isActive():
                self._demo_timer.start(60)
        else:
            self._demo_timer.stop()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        painter = QtGui.QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(12, 12, -12, -12)
        painter.fillRect(self.rect(), QtGui.QColor("#0b1224"))

        # Сетка
        painter.setPen(QtGui.QPen(QtGui.QColor("#1f2937"), 1))
        for x in range(rect.left(), rect.right(), max(1, rect.width() // 8)):
            painter.drawLine(x, rect.top(), x, rect.bottom())
        for y in range(rect.top(), rect.bottom(), max(1, rect.height() // 4)):
            painter.drawLine(rect.left(), y, rect.right(), y)

        center = rect.center()
        painter.translate(center)

        # Yaw стрелка (север = -90 градусов)
        yaw_rad = math.radians(self.yaw - 90)
        arrow_len = min(rect.width(), rect.height()) * 0.3
        yaw_end = QtCore.QPointF(arrow_len * math.cos(yaw_rad), arrow_len * math.sin(yaw_rad))
        painter.setPen(QtGui.QPen(QtGui.QColor("#f59e0b"), 3))
        painter.drawLine(QtCore.QPointF(0, 0), yaw_end)

        # Корпус датчика
        painter.rotate(self.roll)
        painter.translate(0, -self.pitch)  # pitch = смещение вдоль Y
        device_rect = QtCore.QRectF(-60, -20, 120, 40)
        painter.setBrush(QtGui.QColor("#1f2937"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#3b82f6"), 2))
        painter.drawRoundedRect(device_rect, 10, 10)

        painter.setPen(QtGui.QColor("#e5e7eb"))
        font = painter.font()
        font.setPointSize(10)
        painter.setFont(font)
        painter.drawText(device_rect, QtCore.Qt.AlignmentFlag.AlignCenter, "CALLIBRI")

        painter.resetTransform()
        info_rect = QtCore.QRect(rect.left(), rect.bottom() - 40, rect.width(), 30)
        painter.setPen(QtGui.QColor("#9ca3af"))
        painter.drawText(
            info_rect,
            QtCore.Qt.AlignmentFlag.AlignCenter,
            f"Pitch {self.pitch:+.1f}°  |  Roll {self.roll:+.1f}°  |  Yaw {self.yaw:+.1f}°",
        )
        painter.end()

    def _tick_demo(self) -> None:
        self.pitch = 10 * math.sin(QtCore.QTime.currentTime().msec() / 180.0)
        self.roll = 15 * math.cos(QtCore.QTime.currentTime().msec() / 160.0)
        self.yaw = (self.yaw + random.uniform(-2, 2)) % 360
        self.update()
