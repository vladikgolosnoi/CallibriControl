"""Основное окно Callibri Control (шаг 5: современный GUI с навигацией/статусом/треем).

Каркас построен на PyQt6: боковая навигация, область контента со страницами,
статус-бар, системный трей и переключение тем (тёмная/светлая).
"""

from __future__ import annotations

import sys
import threading
import contextlib
import os
from pathlib import Path
from typing import Dict, Optional

try:
    from PyQt6 import QtCore, QtGui, QtWidgets
except Exception as exc:  # noqa: BLE001
    raise ImportError("PyQt6 is required for GUI mode. Install from requirements.txt") from exc

from callibri_control.utils.config_manager import ConfigManager
from callibri_control.core.sensor_manager import SensorManager
from callibri_control.ui.sensor_bridge import SensorBridge
from callibri_control.control.profiles import DEFAULT_MAPPINGS
from callibri_control.ui.hud_overlay import HudOverlay
from .pages.analytics_page import AnalyticsPage
from .pages.control_page import ControlPage
from .pages.dashboard import DashboardPage
from .pages.games_page import GamesPage
from .pages.settings_page import SettingsPage
from .pages.training_page import TrainingPage


class MainWindow(QtWidgets.QMainWindow):
    """Главное окно приложения c навигацией и статусом устройства."""

    def __init__(self, config: Optional[ConfigManager] = None, manager: Optional[SensorManager] = None) -> None:
        super().__init__()
        # Отключаем спам qt.text.emojisegmenter
        try:
            QtCore.QLoggingCategory.setFilterRules(
                "qt.text.emojisegmenter.debug=false\n"
                "qt.text.emojisegmenter.info=false\n"
                "qt.text.emojisegmenter=false\n"
                "qt.text=false\n"
            )
        except Exception:
            pass
        self.config = config
        self.sensor_manager = manager
        self.bridge: Optional[SensorBridge] = None
        self.setWindowTitle("Callibri Control")
        self.resize(1280, 820)
        self.setMinimumSize(1100, 720)
        self.setWindowIcon(self._build_icon("CC"))
        self.setUnifiedTitleAndToolBarOnMac(True)

        self._nav_buttons: Dict[str, QtWidgets.QToolButton] = {}
        self._pages: Dict[str, QtWidgets.QWidget] = {}
        self._is_sidebar_collapsed = False
        self._session_timer = QtCore.QElapsedTimer()
        self._session_timer.start()
        self._streaming_active = False
        self._emg_peak = 0.1
        self._control_profile = (
            self.config.config.get("control", {}).get("profile", "DEFAULT") if self.config else "DEFAULT"
        )
        self.hud: Optional[HudOverlay] = None
        self._hud_visible = False

        self._status = {
            "device": "Не подключено",
            "battery": 0,
            "state": "Готов",
            "fatigue": 0,
        }

        self._create_ui()
        self._create_tray()
        self._apply_theme(self._theme_from_config())
        self._setup_shortcuts()

    # UI ------------------------------------------------------------------
    def _create_ui(self) -> None:
        central = QtWidgets.QWidget()
        central.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        # Верхняя панель с брендингом и быстрыми действиями
        header = self._build_header()
        outer.addWidget(header)

        # Основная область: сайдбар + контент
        split = QtWidgets.QHBoxLayout()
        split.setContentsMargins(0, 0, 0, 0)
        split.setSpacing(12)

        self.sidebar = self._build_sidebar()
        split.addWidget(self.sidebar)

        self.stack = QtWidgets.QStackedWidget()
        self.stack.setObjectName("ContentStack")
        split.addWidget(self.stack, 1)

        outer.addLayout(split, 1)

        status = self._build_statusbar()
        outer.addWidget(status)

        self.setCentralWidget(central)
        self._populate_pages()

        # Обновление времени сессии в статус-баре
        self._tick_timer = QtCore.QTimer(self)
        self._tick_timer.timeout.connect(self._tick_status)
        self._tick_timer.start(1000)

    def _build_header(self) -> QtWidgets.QWidget:
        frame = QtWidgets.QFrame()
        frame.setObjectName("Header")
        layout = QtWidgets.QHBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        logo = QtWidgets.QLabel("CALLIBRI CONTROL")
        logo.setObjectName("LogoTitle")
        logo.setAlignment(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(logo)
        layout.addStretch()

        self.theme_toggle = QtWidgets.QComboBox()
        self.theme_toggle.addItems(["dark", "light", "contrast"])
        self.theme_toggle.setCurrentText(self._theme_from_config())
        self.theme_toggle.currentTextChanged.connect(self._apply_theme)
        self.theme_toggle.setToolTip("Тема интерфейса")
        layout.addWidget(self._labeled_wrap("🎨", self.theme_toggle))

        self.hud_btn = QtWidgets.QToolButton()
        self.hud_btn.setText("HUD")
        self.hud_btn.setToolTip("Показать/скрыть HUD поверх всех окон")
        self.hud_btn.setCheckable(True)
        self.hud_btn.clicked.connect(self._toggle_hud)
        layout.addWidget(self.hud_btn)

        self.collapse_btn = QtWidgets.QToolButton()
        self.collapse_btn.setObjectName("CollapseButton")
        self.collapse_btn.setText("←")
        self.collapse_btn.setToolTip("Свернуть/развернуть меню")
        self.collapse_btn.clicked.connect(self._toggle_sidebar)
        layout.addWidget(self.collapse_btn)
        return frame

    def _build_sidebar(self) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setObjectName("Sidebar")
        frame.setMinimumWidth(220)
        frame.setMaximumWidth(220)
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        nav_title = QtWidgets.QLabel("Навигация")
        nav_title.setObjectName("SidebarTitle")
        layout.addWidget(nav_title)

        items = [
            ("dashboard", "🏠", "Главная", DashboardPage),
            ("control", "🎮", "Управление", ControlPage),
            ("training", "💪", "Тренировки", TrainingPage),
            ("games", "🎯", "Игры", GamesPage),
            ("analytics", "📊", "Аналитика", AnalyticsPage),
            ("settings", "⚙️", "Настройки", SettingsPage),
        ]
        for key, icon, title, _cls in items:
            btn = QtWidgets.QToolButton()
            btn.setObjectName("NavButton")
            btn.setText(f"{icon}  {title}")
            btn.setIcon(self._emoji_icon(icon))
            btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.clicked.connect(lambda _=False, page=key: self._switch_page(page))
            layout.addWidget(btn)
            self._nav_buttons[key] = btn

        layout.addStretch()
        return frame

    def _build_statusbar(self) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setObjectName("StatusBar")
        layout = QtWidgets.QHBoxLayout(frame)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(20)

        self.device_label = QtWidgets.QLabel("🔌 Не подключено")
        self.battery_label = QtWidgets.QLabel("🔋 —")
        self.state_label = QtWidgets.QLabel("💪 Готов")
        self.session_label = QtWidgets.QLabel("⏱️ 00:00:00")
        self.fatigue_label = QtWidgets.QLabel("🟢 Усталость: 0%")

        for widget in (
            self.device_label,
            self.battery_label,
            self.state_label,
            self.session_label,
            self.fatigue_label,
        ):
            widget.setObjectName("StatusLabel")
            layout.addWidget(widget)

        layout.addStretch()
        return frame

    def _populate_pages(self) -> None:
        pages = {
            "dashboard": DashboardPage(),
            "control": ControlPage(),
            "training": TrainingPage(),
            "games": GamesPage(),
            "analytics": AnalyticsPage(),
            "settings": SettingsPage(self.theme_toggle),
        }
        for name, widget in pages.items():
            self._pages[name] = widget
            self.stack.addWidget(widget)

        # выбрать главную страницу
        self._nav_buttons["dashboard"].setChecked(True)
        self._switch_page("dashboard")
        self._apply_shadows()
        self._apply_glass()

        # Кнопки быстрого доступа
        dash: DashboardPage = self._pages["dashboard"]  # type: ignore[assignment]
        dash.start_btn.clicked.connect(self.toggle_control)
        dash.games_btn.clicked.connect(lambda: self._switch_page("games"))
        dash.training_btn.clicked.connect(lambda: self._switch_page("training"))
        dash.profiles_btn.clicked.connect(lambda: self._switch_page("settings"))
        dash.calibrate_btn.clicked.connect(self._recalibrate)
        ctrl: ControlPage = self._pages["control"]  # type: ignore[assignment]
        ctrl.set_profile_options(sorted(DEFAULT_MAPPINGS.keys()), self._control_profile)
        ctrl.profile_combo.currentTextChanged.connect(self._set_profile)

    # Status / theme ------------------------------------------------------
    def update_status(self, *, device: Optional[str] = None, battery: Optional[int] = None, state: Optional[str] = None, fatigue: Optional[int] = None) -> None:
        """Обновить отображаемый статус (используется ядром приложения)."""
        if device is not None:
            self._status["device"] = device
        if battery is not None:
            self._status["battery"] = max(0, min(100, battery))
        if state is not None:
            self._status["state"] = state
        if fatigue is not None:
            self._status["fatigue"] = max(0, min(100, fatigue))
        self._render_status()

    def _render_status(self) -> None:
        self.device_label.setText(f"🔌 {self._status['device']}")
        self.battery_label.setText(f"🔋 {self._status['battery']}%")
        self.state_label.setText(f"💪 {self._status['state']}")
        self.fatigue_label.setText(f"🟢 Усталость: {self._status['fatigue']}%")

    def _tick_status(self) -> None:
        elapsed_ms = self._session_timer.elapsed()
        hours = int(elapsed_ms / 3600000)
        minutes = int((elapsed_ms % 3600000) / 60000)
        seconds = int((elapsed_ms % 60000) / 1000)
        self.session_label.setText(f"⏱️ {hours:02d}:{minutes:02d}:{seconds:02d}")

    def _apply_theme(self, theme: str) -> None:
        theme = theme.lower()
        qss_path = Path(__file__).resolve().parent / "styles" / f"{theme}_theme.qss"
        if qss_path.exists():
            qss = qss_path.read_text(encoding="utf-8")
            self.setStyleSheet(qss)
        else:
            self.setStyleSheet("")
        if self.config:
            try:
                self.config.set_config_value("ui.theme", theme)
            except Exception:
                # В GUI режиме не падаем из-за конфигурации — просто игнорируем ошибку
                pass

    def _theme_from_config(self) -> str:
        if self.config:
            ui_cfg = self.config.config.get("ui", {})
            if isinstance(ui_cfg, dict) and ui_cfg.get("theme") in {"dark", "light"}:
                return ui_cfg["theme"]
        return "dark"

    # Navigation / tray ---------------------------------------------------
    def _switch_page(self, name: str) -> None:
        widget = self._pages.get(name)
        if widget is None:
            return
        self.stack.setCurrentWidget(widget)
        self._fade_in(widget)
        if name in self._nav_buttons:
            self._nav_buttons[name].setChecked(True)
        if hasattr(widget, "on_show"):
            try:
                widget.on_show()
            except Exception:
                pass

    def _toggle_sidebar(self) -> None:
        self._is_sidebar_collapsed = not self._is_sidebar_collapsed
        target = 76 if self._is_sidebar_collapsed else 220
        for btn in self._nav_buttons.values():
            btn.setToolButtonStyle(
                QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
                if self._is_sidebar_collapsed
                else QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            )
        anim = QtCore.QPropertyAnimation(self.sidebar, b"maximumWidth", self)
        anim.setDuration(240)
        anim.setStartValue(self.sidebar.width())
        anim.setEndValue(target)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
        anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        self.sidebar.setMinimumWidth(target)

    def _create_tray(self) -> None:
        icon = self.windowIcon()
        self.tray = QtWidgets.QSystemTrayIcon(icon, self)
        self.tray.setToolTip("Callibri Control")
        menu = QtWidgets.QMenu()
        show_action = menu.addAction("Открыть")
        hide_action = menu.addAction("Свернуть в трей")
        menu.addSeparator()
        quit_action = menu.addAction("Выход")

        show_action.triggered.connect(self.showNormal)
        hide_action.triggered.connect(self.hide)
        quit_action.triggered.connect(QtWidgets.QApplication.instance().quit)

        self.tray.setContextMenu(menu)
        self.tray.show()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        """По умолчанию — прячем окно в трей, чтобы управление продолжало работать."""
        if self.tray and self.tray.isVisible():
            event.ignore()
            self.hide()
            self.tray.showMessage("Callibri Control", "Приложение свернуто в трей. Кликните по иконке, чтобы открыть.")
        else:
            super().closeEvent(event)

    # Helpers -------------------------------------------------------------
    def _emoji_icon(self, emoji: str) -> QtGui.QIcon:
        pixmap = QtGui.QPixmap(32, 32)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtCore.Qt.GlobalColor.transparent)
        painter.setBrush(QtGui.QColor("#1f2937"))
        painter.drawRoundedRect(0, 0, 32, 32, 8, 8)
        painter.setPen(QtGui.QPen(QtGui.QColor("#e5e7eb")))
        font = painter.font()
        font.setPointSize(14)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, emoji)
        painter.end()
        return QtGui.QIcon(pixmap)

    def _build_icon(self, text: str) -> QtGui.QIcon:
        pixmap = QtGui.QPixmap(128, 128)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setBrush(QtGui.QColor("#2563eb"))
        painter.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.transparent))
        painter.drawRoundedRect(0, 0, 128, 128, 28, 28)
        painter.setPen(QtGui.QPen(QtGui.QColor("#e5e7eb")))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(46)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
        return QtGui.QIcon(pixmap)

    def _labeled_wrap(self, prefix: str, widget: QtWidgets.QWidget) -> QtWidgets.QFrame:
        wrapper = QtWidgets.QFrame()
        layout = QtWidgets.QHBoxLayout(wrapper)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(6)
        label = QtWidgets.QLabel(prefix)
        layout.addWidget(label)
        layout.addWidget(widget)
        return wrapper

    def _apply_shadows(self) -> None:
        """Отключено: тени иногда вызывают баги QPainter на некоторых системах."""
        return

    def _apply_glass(self) -> None:
        """Помечает карточки как «стекло», чтобы QSS дал полупрозрачный фон/blur."""
        for frame in self.findChildren(QtWidgets.QFrame):
            if frame.objectName() in {"Card", "Header", "Sidebar", "StatusBar"}:
                frame.setProperty("glass", True)

    def _fade_in(self, widget: QtWidgets.QWidget) -> None:
        """Лёгкая анимация появления страниц для «премиум» ощущения."""
        effect = QtWidgets.QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QtCore.QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(200)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutQuad)
        anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _set_demo(self, enabled: bool) -> None:
        dash: DashboardPage = self._pages.get("dashboard")  # type: ignore[assignment]
        control: ControlPage = self._pages.get("control")  # type: ignore[assignment]
        if dash:
            dash.set_demo(enabled)
        if control:
            control.set_demo(enabled)

    def _toggle_hud(self, checked: bool) -> None:
        if self.hud is None:
            self.hud = HudOverlay()
            # применяем стиль текущей темы
            self.hud.setStyleSheet(self.styleSheet())
        self._hud_visible = checked
        if checked:
            self.hud.show()
            self.hud.raise_()
        else:
            self.hud.hide()

    # Shortcuts / actions --------------------------------------------------
    def _setup_shortcuts(self) -> None:
        if not self.config:
            seq = "Ctrl+Alt+S"
        else:
            seq = self.config.keybindings.get("start_stop", "Ctrl+Alt+S")
        QtGui.QShortcut(QtGui.QKeySequence(seq), self, self.toggle_control)

    def start_control(self) -> None:
        if self._streaming_active:
            return
        if self.bridge is None:
            self.bridge = SensorBridge(self.sensor_manager, self.config)
            self.bridge.deviceInfo.connect(self._on_device_info)
            self.bridge.statusText.connect(self._on_status_text)
            self.bridge.emgRms.connect(self._on_emg)
            self.bridge.orientation.connect(self._on_orientation)
            self.bridge.accMagnitude.connect(self._on_acc_mag)
            self.bridge.gestureDetected.connect(self._on_gesture)
            self.bridge.fatigueIndex.connect(self._on_fatigue)
            self.bridge.set_control_profile(self._control_profile)
        self.bridge.start()
        self._set_demo(False)
        self._streaming_active = True
        self._set_start_button_text("Стоп")
        self.update_status(state="Активно")
        self.announce("Старт управления")

    def stop_control(self) -> None:
        if not self._streaming_active:
            return
        if self.bridge:
            self.bridge.stop()
        self._set_demo(True)
        self._streaming_active = False
        self._set_start_button_text("Старт")
        self.update_status(state="Пауза")
        self.announce("Остановлено")

    def toggle_control(self) -> None:
        if self._streaming_active:
            self.stop_control()
        else:
            self.start_control()

    def _recalibrate(self) -> None:
        """Перезапускает поток с быстрой авто-калибровкой."""
        self.stop_control()
        QtCore.QTimer.singleShot(200, self.start_control)

    # Live updates ---------------------------------------------------------
    def _on_device_info(self, info: dict) -> None:
        dashboard: DashboardPage = self._pages.get("dashboard")  # type: ignore[assignment]
        name = info.get("name", "Callibri")
        battery = int(info.get("battery", 0) or 0)
        dashboard.update_device(name, info.get("serial", "—"), info.get("firmware", "—"), battery)
        self.update_status(device=name, battery=battery)

    def _on_status_text(self, text: str, battery: int) -> None:
        self.update_status(device=self._status["device"], battery=battery, state=text)

    def _on_emg(self, rms: float) -> None:
        baseline = 0.0
        span = self._emg_peak or 1e-3
        if self.bridge:
            baseline = getattr(self.bridge.thresholds, "baseline", 0.0)
            span = max(getattr(self.bridge.thresholds, "mvc", 0.1) - baseline, 1e-3)
        self._emg_peak = max(self._emg_peak * 0.995, rms + 1e-6)
        normalized = max(0.0, min((rms - baseline) / span, 1.2))
        dashboard: DashboardPage = self._pages.get("dashboard")  # type: ignore[assignment]
        control: ControlPage = self._pages.get("control")  # type: ignore[assignment]
        dashboard.muscle_bar.set_value(normalized)
        control.muscle_bar.set_value(normalized)
        dashboard.emg_plot.append_point(rms)
        control.emg_plot.append_point(rms)
        if self.hud and self._hud_visible:
            self.hud.update_muscle(normalized)

    def _on_orientation(self, pitch: float, roll: float, yaw: float) -> None:
        dashboard: DashboardPage = self._pages.get("dashboard")  # type: ignore[assignment]
        control: ControlPage = self._pages.get("control")  # type: ignore[assignment]
        dashboard.orientation.set_orientation(pitch, roll, yaw)
        control.tilt_plot.append_point(roll)

    def _on_acc_mag(self, mag: float) -> None:
        # Дополнительный индикатор активности MEMS (shake) можно подсвечивать позже
        pass

    def _on_fatigue(self, idx: float) -> None:
        fatigue = min(int(idx * 100), 100)
        self.update_status(fatigue=fatigue)
        dashboard: DashboardPage = self._pages.get("dashboard")  # type: ignore[assignment]
        dashboard.fatigue.set_value(fatigue)
        if self.hud and self._hud_visible:
            self.hud.update_fatigue(fatigue)

    def _on_gesture(self, event: dict) -> None:
        name = event.get("type", "GESTURE")
        confidence = float(event.get("value", 0.0) or 0.0)
        dashboard: DashboardPage = self._pages.get("dashboard")  # type: ignore[assignment]
        control: ControlPage = self._pages.get("control")  # type: ignore[assignment]
        dashboard.gesture_indicator.set_gesture(str(name), confidence=confidence if confidence <= 1 else min(confidence / 10.0, 1.0))
        control.add_gesture_event(str(name), confidence if confidence <= 1 else min(confidence / 10.0, 1.0))
        # Озвучка на двойном/тройном флексе
        if name in {"DOUBLE_FLEX", "TRIPLE_FLEX"}:
            self.announce(f"{name.replace('_', ' ').title()}")
        if self.hud and self._hud_visible:
            self.hud.update_gesture(str(name), confidence if confidence <= 1 else min(confidence / 10.0, 1.0))

    def _set_profile(self, name: str) -> None:
        self._control_profile = name
        if self.bridge:
            self.bridge.set_control_profile(name)
        ctrl: ControlPage = self._pages.get("control")  # type: ignore[assignment]
        if ctrl and ctrl.profile_combo.currentText() != name:
            ctrl.profile_combo.setCurrentText(name)
        if self.config:
            with contextlib.suppress(Exception):
                self.config.set_config_value("control.profile", name)

    def _set_start_button_text(self, text: str) -> None:
        dashboard: DashboardPage = self._pages.get("dashboard")  # type: ignore[assignment]
        if hasattr(dashboard, "start_btn"):
            dashboard.start_btn.setText(text)
            if text == "Стоп":
                dashboard.start_btn.setObjectName("PrimaryButton")
            dashboard.start_btn.repaint()

    # Voice ----------------------------------------------------------------
    def announce(self, text: str) -> None:
        def _speak(msg: str) -> None:
            try:
                import pyttsx3

                engine = pyttsx3.init()
                engine.setProperty("rate", 180)
                engine.say(msg)
                engine.runAndWait()
            except Exception:
                pass

        threading.Thread(target=_speak, args=(text,), daemon=True).start()


def run_gui(config: Optional[ConfigManager] = None, manager: Optional[SensorManager] = None) -> int:
    """Точка входа для GUI режима (используется из main.py)."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    window = MainWindow(config=config, manager=manager)
    window.show()
    return app.exec()
