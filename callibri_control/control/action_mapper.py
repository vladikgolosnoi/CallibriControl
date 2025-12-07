"""Maps gestures to actions (keyboard/mouse/macros) with profiles and JSON storage."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from callibri_control.control.keyboard_emulator import KeyboardAction, parse_keys
from callibri_control.control.mouse_emulator import MouseAction


Action = Dict[str, object]


@dataclass
class GestureBinding:
    gesture: str
    action: Action


@dataclass
class Profile:
    name: str
    bindings: List[GestureBinding] = field(default_factory=list)


class ActionMapper:
    """
    Хранит профили привязок жест -> действие.
    Поддерживает импорт/экспорт JSON.
    """

    def __init__(self) -> None:
        self.profiles: Dict[str, Profile] = {}
        self.active_profile: Optional[str] = None

    def load_from_file(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        self.profiles.clear()
        for name, bindings in data.items():
            gb_list = [GestureBinding(g, a) for g, a in bindings.items()]
            self.profiles[name] = Profile(name=name, bindings=gb_list)
        if self.profiles:
            self.active_profile = next(iter(self.profiles.keys()))

    def save_to_file(self, path: Path) -> None:
        payload = {
            name: {b.gesture: b.action for b in prof.bindings}
            for name, prof in self.profiles.items()
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def set_active(self, name: str) -> None:
        # Не падаем, если профиль отсутствует — оставляем активный как есть
        if name not in self.profiles:
            return
        self.active_profile = name

    def resolve(self, gesture: str) -> Optional[Action]:
        if self.active_profile is None or self.active_profile not in self.profiles:
            return None
        for b in self.profiles[self.active_profile].bindings:
            if b.gesture == gesture:
                return b.action
        return None

    # Примеры конвертации action dict -> реальный вызов (используется в runtime)
    @staticmethod
    def to_keyboard_action(action: Action) -> KeyboardAction:
        return KeyboardAction(
            kind=action.get("kind", "PRESS"),
            keys=parse_keys(action.get("keys", "")),
            text=action.get("text", ""),
            delay_ms=int(action.get("delay_ms", 30)),
        )

    @staticmethod
    def to_mouse_action(action: Action) -> MouseAction:
        return MouseAction(
            kind=action.get("kind", "MOVE"),
            delta=tuple(action.get("delta", (0, 0))),
            button=action.get("button", "left"),
            scroll=tuple(action.get("scroll", (0, 0))),
        )
