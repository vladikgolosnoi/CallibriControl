"""Пакет страниц интерфейса."""

from .dashboard import DashboardPage
from .control_page import ControlPage
from .training_page import TrainingPage
from .games_page import GamesPage
from .analytics_page import AnalyticsPage
from .settings_page import SettingsPage

__all__ = [
    "DashboardPage",
    "ControlPage",
    "TrainingPage",
    "GamesPage",
    "AnalyticsPage",
    "SettingsPage",
]
