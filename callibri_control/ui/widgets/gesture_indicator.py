"""Виджет крупного индикатора жеста с мягкой анимацией."""

from __future__ import annotations

import math
from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets


class GestureIndicator(QtWidgets.QWidget):
    """Показывает текущий жест, уверенность и пульс-анимацию при срабатывании."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(260, 260)
        self._gesture = "Нет жеста"
        self._confidence = 0.0
        self._flash = 0.0

        self._anim_timer = QtCore.QTimer(self)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start(16)

    def set_gesture(self, gesture: str, confidence: float = 0.0) -> None:
        self._gesture = gesture
        self._confidence = max(0.0, min(1.0, confidence))
        self._flash = 1.0
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        painter = QtGui.QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(10, 10, -10, -10)

        # Фон
        painter.fillRect(self.rect(), QtGui.QColor("#0b1224"))

        # Пульсирующее кольцо
        ring_size = min(rect.width(), rect.height())
        base_radius = ring_size / 2.2
        pulse = self._flash * 14
        center = rect.center()
        gradient = QtGui.QRadialGradient(QtCore.QPointF(center), float(base_radius + pulse))
        gradient.setColorAt(0, QtGui.QColor("#60a5fa"))
        gradient.setColorAt(1, QtGui.QColor(96, 165, 250, int(60 * self._flash)))
        painter.setBrush(QtGui.QBrush(gradient))
        painter.setPen(QtGui.QPen(QtGui.QColor("#1d4ed8"), 2))
        painter.drawEllipse(center, base_radius + pulse, base_radius + pulse)

        # Основной круг
        painter.setBrush(QtGui.QColor("#111827"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#3b82f6"), 2))
        painter.drawEllipse(center, base_radius, base_radius)

        # Текст жеста
        painter.setPen(QtGui.QColor("#e5e7eb"))
        font = painter.font()
        font.setPointSize(22)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, self._gesture)

        # Подпись уверенности
        conf_rect = QtCore.QRect(rect.left(), rect.bottom() - 40, rect.width(), 30)
        font.setPointSize(12)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QtGui.QColor("#9ca3af"))
        painter.drawText(conf_rect, QtCore.Qt.AlignmentFlag.AlignCenter, f"Уверенность: {self._confidence*100:.0f}%")

        painter.end()

    def _tick(self) -> None:
        if self._flash <= 0.0:
            return
        # Экспоненциальное затухание для мягкого эффекта
        self._flash = max(0.0, self._flash - 0.04)
        self.update()
