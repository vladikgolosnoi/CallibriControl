"""Страница игр: лаунчер встроенных мини-игр."""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtWidgets


class GamesPage(QtWidgets.QWidget):
    """Каркас выбора игр и отображения рекордов."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._build_layout()

    def _build_layout(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QtWidgets.QLabel("Игры")
        header.setObjectName("PageTitle")
        layout.addWidget(header)

        grid = QtWidgets.QGridLayout()
        grid.setSpacing(10)
        layout.addLayout(grid)

        games = [
            ("Runner", "Бесконечный раннер как Chrome Dino", "Сложность: ⭐⭐☆", "Рекорд: 0"),
            ("Reaction", "Стреляй по целям жестами", "Сложность: ⭐⭐☆", "Точность: 0%"),
            ("Rhythm", "Попадай в ритм треками", "Сложность: ⭐⭐⭐", "Комбо: 0"),
        ]
        for idx, (title, desc, difficulty, best) in enumerate(games):
            card = self._game_card(title, desc, difficulty, best)
            grid.addWidget(card, idx // 2, idx % 2)

        layout.addStretch()

    def _game_card(self, title: str, desc: str, difficulty: str, best: str) -> QtWidgets.QWidget:
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        vbox = QtWidgets.QVBoxLayout(card)
        vbox.setContentsMargins(12, 12, 12, 12)
        vbox.setSpacing(6)
        title_lbl = QtWidgets.QLabel(title)
        title_lbl.setObjectName("CardTitle")
        vbox.addWidget(title_lbl)
        vbox.addWidget(QtWidgets.QLabel(desc))
        vbox.addWidget(QtWidgets.QLabel(difficulty))
        vbox.addWidget(QtWidgets.QLabel(best))
        btn = QtWidgets.QPushButton("Играть")
        btn.setObjectName("PrimaryButton")
        vbox.addStretch()
        vbox.addWidget(btn)
        return card
