"""Cross-platform mouse emulator using pynput."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from pynput.mouse import Button, Controller


@dataclass
class MouseAction:
    kind: str  # MOVE/MOVE_ABS/CLICK/DOUBLE_CLICK/DRAG/DRAG_END/SCROLL
    delta: Tuple[int, int] = (0, 0)  # для MOVE (относительное) или координаты для MOVE_ABS
    button: str = "left"
    scroll: Tuple[int, int] = (0, 0)  # (dx, dy)


def _btn(name: str):
    name = name.lower()
    if name == "left":
        return Button.left
    if name == "right":
        return Button.right
    if name == "middle":
        return Button.middle
    return Button.left


class MouseEmulator:
    """Эмуляция мыши: перемещение, клики, даблклик, драг, скролл."""

    def __init__(self) -> None:
        self._mouse = Controller()
        self._dragging = False

    def execute(self, action: MouseAction) -> None:
        kind = action.kind.upper()
        if kind == "MOVE":
            self._mouse.move(action.delta[0], action.delta[1])
        elif kind == "MOVE_ABS":
            try:
                self._mouse.position = action.delta
            except Exception:
                # если координаты некорректны/платформа не поддерживает
                self._mouse.move(action.delta[0], action.delta[1])
        elif kind == "CLICK":
            self._mouse.click(_btn(action.button), 1)
        elif kind == "DOUBLE_CLICK":
            self._mouse.click(_btn(action.button), 2)
        elif kind == "DRAG":
            if not self._dragging:
                self._mouse.press(_btn(action.button))
                self._dragging = True
            self._mouse.move(action.delta[0], action.delta[1])
        elif kind == "DRAG_END":
            if self._dragging:
                self._mouse.release(_btn(action.button))
                self._dragging = False
        elif kind == "SCROLL":
            self._mouse.scroll(action.scroll[0], action.scroll[1])
        else:
            raise ValueError(f"Unknown mouse action: {kind}")
