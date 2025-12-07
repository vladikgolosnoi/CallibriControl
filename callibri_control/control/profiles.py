"""Profiles with built-in mappings for common scenarios."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from callibri_control.control.action_mapper import ActionMapper, GestureBinding, Profile


DEFAULT_MAPPINGS: Dict[str, Dict[str, dict]] = {
    "DEFAULT": {
        "MUSCLE_FLEX": {"type": "keyboard", "kind": "PRESS", "keys": "space"},
        "DOUBLE_FLEX": {"type": "keyboard", "kind": "PRESS", "keys": "enter"},
        "TILT_LEFT": {"type": "keyboard", "kind": "PRESS", "keys": "left"},
        "TILT_RIGHT": {"type": "keyboard", "kind": "PRESS", "keys": "right"},
        "SHAKE": {"type": "keyboard", "kind": "PRESS", "keys": "esc"},
    },
    "GAMING_WASD": {
        "MUSCLE_FLEX": {"type": "keyboard", "kind": "PRESS", "keys": "w"},
        "TILT_LEFT": {"type": "keyboard", "kind": "PRESS", "keys": "a"},
        "TILT_RIGHT": {"type": "keyboard", "kind": "PRESS", "keys": "d"},
        "TILT_UP": {"type": "keyboard", "kind": "PRESS", "keys": "w"},
        "TILT_DOWN": {"type": "keyboard", "kind": "PRESS", "keys": "s"},
        "DOUBLE_FLEX": {"type": "keyboard", "kind": "PRESS", "keys": "space"},
    },
    "GAMING_ARROWS": {
        "MUSCLE_FLEX": {"type": "keyboard", "kind": "PRESS", "keys": "up"},
        "TILT_LEFT": {"type": "keyboard", "kind": "PRESS", "keys": "left"},
        "TILT_RIGHT": {"type": "keyboard", "kind": "PRESS", "keys": "right"},
        "TILT_DOWN": {"type": "keyboard", "kind": "PRESS", "keys": "down"},
        "DOUBLE_FLEX": {"type": "keyboard", "kind": "PRESS", "keys": "space"},
    },
    "PRESENTATION": {
        "MUSCLE_FLEX": {"type": "keyboard", "kind": "PRESS", "keys": "right"},
        "DOUBLE_FLEX": {"type": "keyboard", "kind": "PRESS", "keys": "left"},
        # Свайпы: вправо = следующий, влево = предыдущий (перепутано было — исправлено)
        "TILT_LEFT": {"type": "keyboard", "kind": "PRESS", "keys": "pagedown"},   # машем влево — следующий
        "TILT_RIGHT": {"type": "keyboard", "kind": "PRESS", "keys": "pageup"},    # машем вправо — предыдущий
        "FLEX_TILT_LEFT": {"type": "keyboard", "kind": "PRESS", "keys": "pagedown"},
        "FLEX_TILT_RIGHT": {"type": "keyboard", "kind": "PRESS", "keys": "pageup"},
    },
    "MEDIA": {
        "MUSCLE_FLEX": {"type": "keyboard", "kind": "PRESS", "keys": "space"},
        "DOUBLE_FLEX": {"type": "keyboard", "kind": "PRESS", "keys": "right"},
        "TRIPLE_FLEX": {"type": "keyboard", "kind": "PRESS", "keys": "left"},
        "SHAKE": {"type": "keyboard", "kind": "PRESS", "keys": "volume_mute"},
        "MUSCLE_HOLD": {"type": "keyboard", "kind": "HOLD", "keys": "volume_up"},
        "MUSCLE_RELEASE": {"type": "keyboard", "kind": "PRESS", "keys": "volume_down"},
    },
    "BROWSER": {
        "MUSCLE_FLEX": {"type": "keyboard", "kind": "PRESS", "keys": "enter"},
        "DOUBLE_FLEX": {"type": "keyboard", "kind": "PRESS", "keys": "ctrl+l"},
        "TRIPLE_FLEX": {"type": "keyboard", "kind": "PRESS", "keys": "ctrl+t"},
        "TILT_LEFT": {"type": "keyboard", "kind": "PRESS", "keys": "alt+left"},
        "TILT_RIGHT": {"type": "keyboard", "kind": "PRESS", "keys": "alt+right"},
        "TILT_UP": {"type": "keyboard", "kind": "PRESS", "keys": "ctrl+tab"},
        "TILT_DOWN": {"type": "keyboard", "kind": "PRESS", "keys": "ctrl+shift+tab"},
    },
    "ACCESSIBILITY": {
        "MUSCLE_FLEX": {"type": "keyboard", "kind": "PRESS", "keys": "space"},
        "DOUBLE_FLEX": {"type": "keyboard", "kind": "PRESS", "keys": "enter"},
        "TRIPLE_FLEX": {"type": "keyboard", "kind": "PRESS", "keys": "tab"},
        "MUSCLE_HOLD": {"type": "keyboard", "kind": "HOLD", "keys": "shift"},
        "MUSCLE_RELEASE": {"type": "keyboard", "kind": "RELEASE", "keys": "shift"},
        "TILT_LEFT": {"type": "keyboard", "kind": "PRESS", "keys": "left"},
        "TILT_RIGHT": {"type": "keyboard", "kind": "PRESS", "keys": "right"},
        "TILT_UP": {"type": "keyboard", "kind": "PRESS", "keys": "up"},
        "TILT_DOWN": {"type": "keyboard", "kind": "PRESS", "keys": "down"},
    },
    "MOUSE_CONTROL": {
        "MUSCLE_FLEX": {"type": "mouse", "kind": "CLICK", "button": "left"},
        "DOUBLE_FLEX": {"type": "mouse", "kind": "DOUBLE_CLICK", "button": "left"},
        "TRIPLE_FLEX": {"type": "mouse", "kind": "CLICK", "button": "right"},
        "MUSCLE_HOLD": {"type": "mouse", "kind": "DRAG"},
        "MUSCLE_RELEASE": {"type": "mouse", "kind": "DRAG_END"},
        "SHAKE": {"type": "mouse", "kind": "SCROLL", "scroll": (0, -3)},
    },
}


class ProfileManager:
    """Manage built-in and custom control profiles."""

    def __init__(self, storage: Path | None = None) -> None:
        self.mapper = ActionMapper()
        self.storage = storage
        self._load_defaults()
        if storage:
            self.mapper.load_from_file(storage)
        if self.mapper.profiles and self.mapper.active_profile is None:
            self.mapper.active_profile = "DEFAULT"

    def _load_defaults(self) -> None:
        for name, mapping in DEFAULT_MAPPINGS.items():
            bindings = [GestureBinding(g, a) for g, a in mapping.items()]
            self.mapper.profiles[name] = Profile(name=name, bindings=bindings)
        if self.mapper.profiles and self.mapper.active_profile is None:
            self.mapper.active_profile = "DEFAULT"

    def save(self) -> None:
        if self.storage:
            self.mapper.save_to_file(self.storage)

    def list_profiles(self):
        return list(self.mapper.profiles.keys())

    def set_active(self, name: str) -> None:
        self.mapper.set_active(name)
        self.save()

    def get_action(self, gesture: str) -> dict | None:
        return self.mapper.resolve(gesture)

    def add_profile(self, name: str, mapping: Dict[str, dict]) -> None:
        bindings = [GestureBinding(g, a) for g, a in mapping.items()]
        self.mapper.profiles[name] = Profile(name=name, bindings=bindings)
        self.save()
