"""Cross-platform keyboard emulator using pynput."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable, List, Optional

from pynput.keyboard import Controller, Key


KeySpec = List[str]  # e.g. ["ctrl", "alt", "s"] or ["space"]


def _normalize_key(name: str):
    name = name.lower()
    special = {
        "enter": Key.enter,
        "return": Key.enter,
        "space": Key.space,
        "tab": Key.tab,
        "esc": Key.esc,
        "escape": Key.esc,
        "backspace": Key.backspace,
        "delete": Key.delete,
        "del": Key.delete,
        "insert": getattr(Key, "insert", None),
        "home": Key.home,
        "end": Key.end,
        "pageup": Key.page_up,
        "pagedown": Key.page_down,
        "up": Key.up,
        "down": Key.down,
        "left": Key.left,
        "right": Key.right,
        "capslock": Key.caps_lock,
        "ctrl": Key.ctrl,
        "control": Key.ctrl,
        "alt": Key.alt,
        "option": getattr(Key, "alt_l", Key.alt),
        "shift": Key.shift,
        "cmd": getattr(Key, "cmd", getattr(Key, "cmd_l", None)),
        "win": getattr(Key, "cmd", getattr(Key, "cmd_l", None)),
        "meta": getattr(Key, "cmd", getattr(Key, "cmd_l", None)),
        "f1": Key.f1,
        "f2": Key.f2,
        "f3": Key.f3,
        "f4": Key.f4,
        "f5": Key.f5,
        "f6": Key.f6,
        "f7": Key.f7,
        "f8": Key.f8,
        "f9": Key.f9,
        "f10": Key.f10,
        "f11": Key.f11,
        "f12": Key.f12,
        "printscreen": getattr(Key, "print_screen", None),
        "scrolllock": getattr(Key, "scroll_lock", None),
        "pause": getattr(Key, "pause", None),
        "media_play": getattr(Key, "media_play_pause", None),
        "media_pause": getattr(Key, "media_play_pause", None),
        "media_next": getattr(Key, "media_next", None),
        "media_prev": getattr(Key, "media_previous", None),
        "volume_up": getattr(Key, "volume_up", None),
        "volume_down": getattr(Key, "volume_down", None),
        "volume_mute": getattr(Key, "media_volume_mute", getattr(Key, "mute", None)),
    }
    key_obj = special.get(name)
    return key_obj if key_obj is not None else name


def parse_keys(spec: str) -> KeySpec:
    """Parses 'ctrl+alt+s' -> ['ctrl','alt','s']"""
    return [part.strip() for part in spec.replace("+", " ").split() if part.strip()]


@dataclass
class KeyboardAction:
    kind: str  # PRESS/HOLD/RELEASE/COMBO/SEQUENCE/TOGGLE/TYPE_TEXT
    keys: KeySpec
    text: str = ""
    delay_ms: int = 30


class KeyboardEmulator:
    """
    Эмуляция клавиатурных действий: нажатие, удержание, комбо, текст.
    Основано на pynput, кроссплатформенно.
    """

    def __init__(self) -> None:
        self._kb = Controller()
        self._toggles: dict[str, bool] = {}

    def _press_keys(self, keys: Iterable[str]) -> None:
        for k in keys:
            key_obj = _normalize_key(k)
            self._kb.press(key_obj)

    def _release_keys(self, keys: Iterable[str]) -> None:
        for k in keys:
            key_obj = _normalize_key(k)
            self._kb.release(key_obj)

    def execute(self, action: KeyboardAction) -> None:
        kind = action.kind.upper()
        if kind == "PRESS":
            self._press_keys(action.keys)
            self._release_keys(action.keys)
        elif kind == "HOLD":
            self._press_keys(action.keys)
        elif kind == "RELEASE":
            self._release_keys(action.keys)
        elif kind == "COMBO":
            self._press_keys(action.keys)
            self._release_keys(reversed(action.keys))
        elif kind == "SEQUENCE":
            for k in action.keys:
                self._press_keys([k])
                self._release_keys([k])
                time.sleep(action.delay_ms / 1000.0)
        elif kind == "TOGGLE":
            tag = "+".join(action.keys)
            if not self._toggles.get(tag):
                self._press_keys(action.keys)
                self._toggles[tag] = True
            else:
                self._release_keys(action.keys)
                self._toggles[tag] = False
        elif kind == "TYPE_TEXT":
            self._kb.type(action.text)
        else:
            raise ValueError(f"Unknown keyboard action: {kind}")
