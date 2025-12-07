"""Страница настроек с основными секциями (интерфейс, датчик, уведомления)."""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtWidgets


class SettingsPage(QtWidgets.QWidget):
    """Быстрые настройки без погружения в низкоуровневые детали."""

    def __init__(self, theme_control: Optional[QtWidgets.QComboBox] = None, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._build_layout(theme_control)

    def _build_layout(self, theme_control: Optional[QtWidgets.QComboBox]) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QtWidgets.QLabel("Настройки")
        header.setObjectName("PageTitle")
        layout.addWidget(header)

        sections = QtWidgets.QHBoxLayout()
        sections.setSpacing(12)
        sections.addWidget(self._connection_group(), 1)
        sections.addWidget(self._recognition_group(), 1)
        sections.addWidget(self._interface_group(theme_control), 1)
        layout.addLayout(sections)

        layout.addWidget(self._notifications_group())
        layout.addStretch()

    def _connection_group(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Подключение")
        form = QtWidgets.QFormLayout(box)
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        autoconnect = QtWidgets.QCheckBox("Автоподключение")
        form.addRow("Автоподключение", autoconnect)
        timeout = QtWidgets.QSpinBox()
        timeout.setRange(1, 30)
        timeout.setValue(5)
        form.addRow("Таймаут поиска (с)", timeout)
        reconnect = QtWidgets.QCheckBox("Автопереподключение")
        reconnect.setChecked(True)
        form.addRow("Переподключение", reconnect)
        return box

    def _recognition_group(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Распознавание")
        form = QtWidgets.QFormLayout(box)
        profile = QtWidgets.QComboBox()
        profile.addItems(["ULTRA_SENSITIVE", "SENSITIVE", "NORMAL", "GAMING", "PRECISE"])
        form.addRow("Чувствительность", profile)
        debounce = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        debounce.setRange(50, 600)
        debounce.setValue(250)
        form.addRow("Debounce (мс)", debounce)
        min_conf = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        min_conf.setRange(10, 100)
        min_conf.setValue(60)
        form.addRow("Мин. уверенность", min_conf)
        return box

    def _interface_group(self, theme_control: Optional[QtWidgets.QComboBox]) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Интерфейс")
        form = QtWidgets.QFormLayout(box)
        if theme_control:
            form.addRow("Тема", theme_control)
        font_size = QtWidgets.QComboBox()
        font_size.addItems(["Маленький", "Стандарт", "Крупный"])
        form.addRow("Шрифт", font_size)
        animations = QtWidgets.QCheckBox("Анимации")
        animations.setChecked(True)
        form.addRow("Анимации", animations)
        return box

    def _notifications_group(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Уведомления и звуки")
        form = QtWidgets.QFormLayout(box)
        fatigue = QtWidgets.QCheckBox("Предупреждать об усталости")
        fatigue.setChecked(True)
        form.addRow("Усталость", fatigue)
        battery = QtWidgets.QCheckBox("Низкий заряд")
        battery.setChecked(True)
        form.addRow("Батарея", battery)
        sounds = QtWidgets.QCheckBox("Звуки жестов")
        form.addRow("Звуки", sounds)
        return box
