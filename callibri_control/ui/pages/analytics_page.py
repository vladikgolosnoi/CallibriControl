"""Страница аналитики: сводки и мини-графики."""

from __future__ import annotations

import random
from typing import Optional

from PyQt6 import QtCore, QtWidgets

from callibri_control.ui.widgets import SignalPlot


class AnalyticsPage(QtWidgets.QWidget):
    """Базовая визуализация статистики с демо-данными."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._demo_timer = QtCore.QTimer(self)
        self._demo_timer.timeout.connect(self._tick_demo)
        self._demo_timer.start(120)
        self._build_layout()

    def _build_layout(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QtWidgets.QLabel("Аналитика")
        header.setObjectName("PageTitle")
        layout.addWidget(header)

        cards = QtWidgets.QHBoxLayout()
        cards.setSpacing(10)
        for title, value in (
            ("Сессии", "12"),
            ("Время", "02:14:33"),
            ("Успешные жесты", "94%"),
            ("Ложные срабатывания", "3%"),
        ):
            cards.addWidget(self._stat_card(title, value))
        layout.addLayout(cards)

        charts = QtWidgets.QHBoxLayout()
        charts.setSpacing(12)
        self.usage_plot = SignalPlot(demo_mode=True)
        self.usage_plot.setObjectName("Card")
        self.fatigue_plot = SignalPlot(demo_mode=True)
        self.fatigue_plot.setObjectName("Card")
        charts.addWidget(self._chart_wrap("Использование жестов", self.usage_plot))
        charts.addWidget(self._chart_wrap("Динамика усталости", self.fatigue_plot))
        layout.addLayout(charts, 1)
        layout.addStretch()

    def _stat_card(self, title: str, value: str) -> QtWidgets.QWidget:
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        vbox = QtWidgets.QVBoxLayout(card)
        vbox.setContentsMargins(12, 12, 12, 12)
        vbox.setSpacing(4)
        label = QtWidgets.QLabel(title)
        label.setObjectName("SecondaryText")
        val_lbl = QtWidgets.QLabel(value)
        val_lbl.setObjectName("CardTitle")
        vbox.addWidget(label)
        vbox.addWidget(val_lbl)
        return card

    def _chart_wrap(self, title: str, plot: QtWidgets.QWidget) -> QtWidgets.QWidget:
        frame = QtWidgets.QFrame()
        frame.setObjectName("Card")
        vbox = QtWidgets.QVBoxLayout(frame)
        vbox.setContentsMargins(12, 12, 12, 12)
        vbox.setSpacing(6)
        vbox.addWidget(QtWidgets.QLabel(title))
        vbox.addWidget(plot)
        return frame

    def _tick_demo(self) -> None:
        self.usage_plot.append_point(random.uniform(0.3, 1.0))
        self.fatigue_plot.append_point(random.uniform(0.2, 0.9))
