"""Страница тренировок: список упражнений и быстрый старт."""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtWidgets


class TrainingPage(QtWidgets.QWidget):
    """Каркас UI для выбора/запуска тренировок."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._build_layout()

    def _build_layout(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QtWidgets.QLabel("Тренажёр мышц")
        header.setObjectName("PageTitle")
        layout.addWidget(header)

        grid = QtWidgets.QGridLayout()
        grid.setSpacing(10)
        layout.addLayout(grid)

        exercises = [
            ("Удержание", "Держи целевую силу N секунд", "Запустить"),
            ("Повторения", "Циклы сжатие/расслабление", "Начать"),
            ("Градиент", "Плавный набор/сброс силы", "Визуализация"),
            ("Ритм", "Работа в заданном BPM", "Старт"),
            ("Реакция", "Сжать как можно быстрее", "Готов"),
            ("Выносливость", "Держать минимум как можно дольше", "Запуск"),
        ]
        for idx, (title, desc, cta) in enumerate(exercises):
            card = self._exercise_card(title, desc, cta)
            r, c = divmod(idx, 3)
            grid.addWidget(card, r, c)

        layout.addStretch()

    def _exercise_card(self, title: str, desc: str, cta: str) -> QtWidgets.QWidget:
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        vbox = QtWidgets.QVBoxLayout(card)
        vbox.setContentsMargins(12, 12, 12, 12)
        vbox.setSpacing(6)
        label = QtWidgets.QLabel(title)
        label.setObjectName("CardTitle")
        vbox.addWidget(label)
        vbox.addWidget(QtWidgets.QLabel(desc))
        btn = QtWidgets.QPushButton(cta)
        btn.setObjectName("GhostButton")
        vbox.addStretch()
        vbox.addWidget(btn)
        return card
