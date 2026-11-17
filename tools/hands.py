import functools
import json
import math
import time
import pyautogui

import config
from core import desktop, safety
from . import tool, STATE

pyautogui.FAILSAFE = True    # mouse in the top-left corner = emergency stop
pyautogui.PAUSE = 0.05

BLOCKED_KEYS = {"delete", "del"}
BLOCKED_COMBOS = [
    {"alt", "f4"}, {"ctrl", "alt", "delete"}, {"ctrl", "alt", "del"},
    {"ctrl", "shift", "esc"}, {"win", "r"}, {"win", "l"},
    {"ctrl", "enter"}, {"ctrl", "return"},
]


def _stop(reason):
    STATE["abort"] = True
    return f"Stopped: {reason}."


def guarded(func):
    """Kill-switch check before and after every hand action, plus a small pause."""
    @functools.wraps(func)
    def inner(*args, **kwargs):
        if safety.killed():
            return _stop("Esc was pressed (kill switch)")
        try:
            result = func(*args, **kwargs)
        except pyautogui.FailSafeException:
            return _stop("mouse moved to the top-left corner (kill switch)")
        except desktop.TypingAborted as e:
            return _stop(f"typing cancelled ({e})")
        if safety.killed():
            return _stop("Esc was pressed (kill switch)")
        time.sleep(config.ACTION_DELAY)
        return result
    return inner


def _point(x, y):
    """Validate a screen position. Never returns (0, 0) because that is the kill corner."""
    x, y = int(float(x)), int(float(y))
    w, h = pyautogui.size()
    if not (0 <= x < w and 0 <= y < h):
        raise ValueError(f"({x}, {y}) is outside the screen ({w}x{h})")
    return max(x, 1), max(y, 1)


def _go(x, y):
    """Glide to (x, y) if given. Returns the current pointer position."""
    if x is not None and y is not None:
        x, y = _point(x, y)
        pyautogui.moveTo(x, y, duration=config.MOVE_DURATION)
    p = pyautogui.position()
    return p.x, p.y


def _parse_keys(keys):
    return [p.strip().lower() for p in keys.replace(" ", "").split("+") if p.strip()]


# ---------------- read-only ----------------
@tool("Get the screen size in pixels.")
def get_screen_size():
    w, h = pyautogui.size()
    return f"{w}x{h}"


@tool("Get the current mouse pointer position.")
def get_mouse_position():
    p = pyautogui.position()
    return f"x={p.x}, y={p.y}"


# ---------------- mouse ----------------
_XY = {
    "x": {"type": "integer", "description": "Horizontal position in pixels"},
    "y": {"type": "integer", "description": "Vertical position in pixels"},
}


@tool("Move the mouse pointer to screen position (x, y).", parameters=_XY, required=["x", "y"])
@guarded
def mouse_move(x, y):
    x, y = _point(x, y)
    pyautogui.moveTo(x, y, duration=config.MOVE_DURATION)
    return f"Mouse moved to ({x}, {y})"


@tool("Left-click. If x and y are given, move there first; otherwise click where the pointer is.", parameters=_XY)
@guarded
def click(x=None, y=None):
    px, py = _go(x, y)
    pyautogui.click()
    return f"Clicked at ({px}, {py})"


@tool("Double-click. If x and y are given, move there first.", parameters=_XY)
@guarded
def double_click(x=None, y=None):
    px, py = _go(x, y)
    pyautogui.doubleClick()
    return f"Double-clicked at ({px}, {py})"


@tool("Right-click. If x and y are given, move there first.", parameters=_XY)
@guarded
def right_click(x=None, y=None):
    px, py = _go(x, y)
    pyautogui.rightClick()
    return f"Right-clicked at ({px}, {py})"


def _densify(pts, step):
    """Insert intermediate points so the pointer moves in small steps."""
    out = [pts[0]]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(x2 - x1, y2 - y1) / step))
        for i in range(1, n + 1):
            out.append((round(x1 + (x2 - x1) * i / n), round(y1 + (y2 - y1) * i / n)))
    return out

@tool(
    "Press the left mouse button at the first point, drag through all the points in order, "
    "then release. Use for drawing or dragging things.",
    parameters={
        "points": {
            "type": "array",
            "items": {"type": "array", "items": {"type": "integer"}},
            "description": "List of [x, y] points, at least 2, e.g. [[100,100],[300,100]]",
        }
    },
    required=["points"],
)
@guarded
def drag_path(points):
    if isinstance(points, str):
        points = json.loads(points)
    pts = [_point(p[0], p[1]) for p in points]
    if len(pts) < 2:
        raise ValueError("need at least 2 points")
    path = _densify(pts, config.DRAG_POINT_STEP)

    pyautogui.moveTo(pts[0][0], pts[0][1], duration=config.MOVE_DURATION)
    desktop.mouse_move_to(*pts[0])
    time.sleep(0.3)
    desktop.mouse_down()
    time.sleep(0.3)                      # let the app register the press
    try:
        for x, y in path[1:]:
            if safety.killed():
                break
            desktop.mouse_move_to(x, y)
            time.sleep(config.DRAG_EVENT_DELAY)
    finally:
        time.sleep(0.2)
        desktop.mouse_up()
    return f"Dragged through {len(pts)} points ({len(path)} mouse steps)"


@tool(
    "Scroll the mouse wheel. Positive scrolls up, negative scrolls down (3 is a few lines). "
    "Optionally move to (x, y) first.",
    parameters={"amount": {"type": "integer", "description": "Wheel notches, e.g. -3"}, **_XY},
    required=["amount"],
)
@guarded
def scroll(amount, x=None, y=None):
    _go(x, y)
    pyautogui.scroll(int(amount) * 120)   # Windows wheel: 120 units = one notch
    return f"Scrolled {amount}"


# ---------------- keyboard ----------------
@tool(
    "Type text at the current cursor position, like a human typing.",
    parameters={"text": {"type": "string", "description": "The text to type"}},
    required=["text"],
)
@guarded
def type_text(text):
    text = str(text)
    desktop.type_text(text, delay=config.TYPE_DELAY)
    return f"Typed {len(text)} characters"


@tool(
    "Press one key, e.g. enter, tab, esc, space, backspace, up, down, left, right, f2.",
    parameters={"key": {"type": "string", "description": "Key name"}},
    required=["key"],
)
@guarded
def press_key(key):
    k = str(key).strip().lower()
    if k in BLOCKED_KEYS:
        return f"Blocked: the '{k}' key is not allowed yet."
    if k not in pyautogui.KEYBOARD_KEYS:
        return f"Error: unknown key '{k}'."
    pyautogui.press(k)
    return f"Pressed {k}"


@tool(
    "Press a key combination, written with plus signs, e.g. ctrl+c, ctrl+v, ctrl+shift+n.",
    parameters={"keys": {"type": "string", "description": "Combination like ctrl+c"}},
    required=["keys"],
)
@guarded
def hotkey(keys):
    parts = _parse_keys(str(keys))
    if not parts:
        return "Error: no keys given."
    if set(parts) & BLOCKED_KEYS or any(b <= set(parts) for b in BLOCKED_COMBOS):
        return f"Blocked: the combination '{keys}' is not allowed."
    bad = [p for p in parts if p not in pyautogui.KEYBOARD_KEYS]
    if bad:
        return f"Error: unknown key(s) {bad}."
    pyautogui.hotkey(*parts, interval=0.1)
    return f"Pressed {'+'.join(parts)}"


@tool(
    "Wait for a number of seconds (maximum 10).",
    parameters={"seconds": {"type": "number", "description": "Seconds to wait"}},
    required=["seconds"],
)
@guarded
def wait(seconds):
    end = time.time() + min(max(float(seconds), 0), 10)
    while time.time() < end and not safety.killed():
        time.sleep(0.1)
    return f"Waited {seconds}s"