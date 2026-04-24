"""
position_capture.py — Global hotkey position capture for the GunBound shot calculator.

Captures the mouse cursor position when hotkeys are pressed (even when the game window
has focus) and computes SD, height difference, and shot direction for the calculator.

Requirements (optional — graceful degradation if absent):
    pip install pynput        (or pip install -e ".[tools]")

Usage:
    state = CaptureState()
    start_listener(state)   # starts background daemon thread
    # ... player presses Ctrl+1 then Ctrl+2 in the game window ...
    pair = state.consume()
    if pair and pair.is_valid:
        sd          = pair.target_slices * 0.125
        height_diff = pair.height_slices * 0.125
        shoot_right = pair.shoot_right
"""

from __future__ import annotations

import ctypes
import threading
from dataclasses import dataclass, field

from .constants import HOTKEY_OWN, HOTKEY_TARGET

# ── Pixel-to-SD scale (matches tools/gen_ruler.py TICK_PX = 200) ──────────────
_PIXELS_PER_SLICE: int = 200   # 200 px = 0.125 SD = 1 slice
_PIXELS_PER_SD:   int = 1600   # 1600 px = 1.0 SD

# ── Validation ranges (same as cli.py manual input ranges) ────────────────────
_SLICE_MIN: float = 0.8
_SLICE_MAX: float = 24.0
_HEIGHT_MIN: float = -8.0
_HEIGHT_MAX: float = 8.0

# ── pynput import (optional) ──────────────────────────────────────────────────
try:
    from pynput import keyboard as _pynput_keyboard
    HAS_PYNPUT: bool = True
except ImportError:
    HAS_PYNPUT = False
    _pynput_keyboard = None  # type: ignore[assignment]

# ── DPI awareness (per-monitor) ───────────────────────────────────────────────
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# ── Win32 cursor position ─────────────────────────────────────────────────────

class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _get_cursor_pos() -> tuple[int, int]:
    """Return current mouse cursor position as (x, y) in physical screen pixels."""
    pt = _POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


# ── PositionPair ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PositionPair:
    """
    Immutable snapshot of two captured screen positions.
    Provides computed game-unit values via properties.
    """
    own: tuple[int, int]      # (x, y) of player's character in screen pixels
    target: tuple[int, int]   # (x, y) of enemy in screen pixels

    @property
    def dx(self) -> int:
        """Signed horizontal offset: positive = target is to the right of own."""
        return self.target[0] - self.own[0]

    @property
    def dy(self) -> int:
        """
        Signed vertical offset: positive = target is lower on screen
        (= own is higher = positive height_diff in GunBound convention).
        """
        return self.target[1] - self.own[1]

    @property
    def target_slices(self) -> float:
        """Horizontal SD distance in slices (1 slice = 0.125 SD)."""
        return abs(self.dx) / _PIXELS_PER_SLICE

    @property
    def height_slices(self) -> float:
        """
        Height difference in slices (positive = own is higher than enemy).
        Matches cli.py convention: positive height_diff = player is higher.
        """
        return self.dy / _PIXELS_PER_SLICE

    @property
    def shoot_right(self) -> bool:
        """True if the target is to the right of the player's position."""
        return self.dx > 0

    @property
    def is_valid(self) -> bool:
        """
        True if captured values are within the acceptable input ranges used by cli.py.
        Zero horizontal distance is always invalid (cannot compute SD).
        """
        return (
            abs(self.dx) > 0
            and _SLICE_MIN <= self.target_slices <= _SLICE_MAX
            and _HEIGHT_MIN <= self.height_slices <= _HEIGHT_MAX
        )


# ── CaptureState ──────────────────────────────────────────────────────────────

@dataclass
class CaptureState:
    """
    Thread-safe shared state for position capture.

    Written by the background hotkey listener thread (set_own / set_target).
    Read and reset by the main CLI thread (is_complete / consume / reset).
    """
    _own_pos: tuple[int, int] | None = field(default=None, init=False)
    _target_pos: tuple[int, int] | None = field(default=None, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def set_own(self, x: int, y: int) -> None:
        """
        Record own character position. Clears any previously recorded target position
        so that Ctrl+1 always starts a fresh capture pair.
        """
        with self._lock:
            self._own_pos = (x, y)
            self._target_pos = None

    def set_target(self, x: int, y: int) -> None:
        """Record target (enemy) position."""
        with self._lock:
            self._target_pos = (x, y)

    def is_complete(self) -> bool:
        """True if both positions have been captured."""
        with self._lock:
            return self._own_pos is not None and self._target_pos is not None

    def consume(self) -> PositionPair | None:
        """
        If both positions are captured, build and return a PositionPair then reset
        the state to empty. Returns None if capture is incomplete.
        """
        with self._lock:
            if self._own_pos is None or self._target_pos is None:
                return None
            pair = PositionPair(own=self._own_pos, target=self._target_pos)
            self._own_pos = None
            self._target_pos = None
            return pair

    def reset(self) -> None:
        """Clear all captured positions."""
        with self._lock:
            self._own_pos = None
            self._target_pos = None


# ── Listener ──────────────────────────────────────────────────────────────────

def start_listener(state: CaptureState) -> object | None:
    """
    Start a background daemon hotkey listener using pynput.

    Binds Ctrl+1 (HOTKEY_OWN) and Ctrl+2 (HOTKEY_TARGET) as global hotkeys that
    respond while any window (including the game window) has focus.

    Returns the listener object if started, None if pynput is unavailable.
    The listener thread is a daemon — it exits automatically when the main process ends.
    """
    if not HAS_PYNPUT:
        return None

    def _on_own() -> None:
        x, y = _get_cursor_pos()
        state.set_own(x, y)
        print(f"\n  [Capture] Own position recorded ({x}, {y})", flush=True)

    def _on_target() -> None:
        x, y = _get_cursor_pos()
        state.set_target(x, y)
        print(f"\n  [Capture] Target position recorded ({x}, {y})", flush=True)

    listener = _pynput_keyboard.GlobalHotKeys({
        HOTKEY_OWN:    _on_own,
        HOTKEY_TARGET: _on_target,
    })
    listener.daemon = True
    listener.start()
    return listener
