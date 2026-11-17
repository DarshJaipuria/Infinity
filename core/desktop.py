import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32   # Windows only

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12      # Alt
VK_ESCAPE = 0x1B
VK_DELETE = 0x2E
VK_A = 0x41
VK_S = 0x53


class TypingAborted(Exception):
    pass


# ---------- Windows structures for SendInput ----------
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]


# ---------- low-level keys ----------
def _send(vk=0, scan=0, flags=0):
    inp = INPUT(type=INPUT_KEYBOARD, u=_INPUT_UNION(ki=KEYBDINPUT(vk, scan, flags, 0, 0)))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def press(vk):
    _send(vk)
    time.sleep(0.02)
    _send(vk, flags=KEYEVENTF_KEYUP)


def hotkey(*vks):
    for vk in vks:
        _send(vk)
        time.sleep(0.04)
    time.sleep(0.04)
    for vk in reversed(vks):
        _send(vk, flags=KEYEVENTF_KEYUP)
        time.sleep(0.02)


def _type_char(ch):
    data = ch.encode("utf-16-le")
    for i in range(0, len(data), 2):
        unit = int.from_bytes(data[i:i + 2], "little")
        _send(0, unit, KEYEVENTF_UNICODE)
        time.sleep(0.002)
        _send(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)


# ---------- windows ----------
def _title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def foreground_title():
    return _title(user32.GetForegroundWindow())


def find_window(text):
    found = []

    def callback(hwnd, lparam):
        if user32.IsWindowVisible(hwnd) and text.lower() in _title(hwnd).lower():
            found.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found[0] if found else None


def wait_for_window(text, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        hwnd = find_window(text)
        if hwnd:
            return hwnd
        time.sleep(0.3)
    return None


def focus_window(hwnd):
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)          # restore if minimized
    # Tap Shift instead of Alt (VK_MENU) so we never activate Notepad's menu bar
    _send(VK_SHIFT)
    _send(VK_SHIFT, flags=KEYEVENTF_KEYUP)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    return user32.GetForegroundWindow() == hwnd


# ---------- remember the terminal so we can come back to it ----------
_terminal = None


def remember_terminal():
    global _terminal
    _terminal = user32.GetForegroundWindow()


def return_to_terminal():
    if _terminal:
        focus_window(_terminal)


# ---------- visible typing ----------
def type_text(text, delay=0.012, expect_title=None):
    """Type text like a human. Esc stops it. Stops if the window loses focus."""
    text = text.replace("\r\n", "\n")
    for i, ch in enumerate(text):
        if user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000:
            raise TypingAborted("Esc pressed")

        if expect_title and (ch == "\n" or i % 20 == 0):
            fg = foreground_title().lower()
            if expect_title.lower() not in fg and "notepad" not in fg:
                raise TypingAborted("the editor window lost focus")

        if ch == "\n":
            time.sleep(max(delay, 0.015))
            press(VK_RETURN)
            time.sleep(max(delay * 1.5, 0.02))
        elif ch == "\t":
            press(VK_TAB)
            time.sleep(delay)
        else:
            _type_char(ch)
            time.sleep(delay)

# ---------- real mouse input (modern apps need this) ----------
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000


def _mouse(dx=0, dy=0, flags=0):
    inp = INPUT(type=INPUT_MOUSE, u=_INPUT_UNION(mi=MOUSEINPUT(dx, dy, 0, flags, 0, 0)))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def mouse_move_to(x, y):
    """Move the pointer using genuine mouse input (not SetCursorPos)."""
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    nx = round(x * 65535 / (w - 1))
    ny = round(y * 65535 / (h - 1))
    _mouse(nx, ny, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)


def mouse_down():
    _mouse(flags=MOUSEEVENTF_LEFTDOWN)


def mouse_up():
    _mouse(flags=MOUSEEVENTF_LEFTUP)


# ---------- terminal position (used to hide it from screenshots) ----------
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]


def terminal_rect():
    if not _terminal:
        return None
    rect = wintypes.RECT()
    if not user32.GetWindowRect(_terminal, ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom

# ---------- window helpers for File Explorer ----------
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.GetDpiForWindow.argtypes = [wintypes.HWND]


def window_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def windows_of_class(cls):
    found = []

    def callback(hwnd, lparam):
        if user32.IsWindowVisible(hwnd) and window_class(hwnd) == cls:
            found.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found


def is_window(hwnd):
    return bool(hwnd) and bool(user32.IsWindow(hwnd))


def is_foreground(hwnd):
    return user32.GetForegroundWindow() == hwnd


def window_rect(hwnd):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def dpi_scale(hwnd):
    try:
        return user32.GetDpiForWindow(hwnd) / 96
    except Exception:
        return 1.0


# ---------- which parts of the terminal are really visible (not covered by other windows) ----------
GA_ROOT = 2
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND


def terminal_visible_cells(cols=60, rows=40):
    """Small rectangles of the terminal window that are really on top (not hidden behind other windows)."""
    rect = terminal_rect()
    if not rect or not _terminal:
        return []
    l, t, r, b = rect
    cw = max(1.0, (r - l) / cols)
    ch = max(1.0, (b - t) / rows)
    cells = []
    for i in range(rows):
        for j in range(cols):
            x0 = l + j * cw
            y0 = t + i * ch
            hwnd = user32.WindowFromPoint(wintypes.POINT(int(x0 + cw / 2), int(y0 + ch / 2)))
            if hwnd and user32.GetAncestor(hwnd, GA_ROOT) == _terminal:
                cells.append((int(x0), int(y0), int(x0 + cw) + 1, int(y0 + ch) + 1))
    return cells


# ---------- window helpers ----------
def windows_matching(predicate):
    """All visible windows whose title satisfies predicate(title)."""
    found = []

    def callback(hwnd, lparam):
        if user32.IsWindowVisible(hwnd) and predicate(_title(hwnd)):
            found.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found


def minimize_terminal():
    if _terminal:
        user32.ShowWindow(_terminal, 6)   # SW_MINIMIZE


def root_window_at(x, y):
    """The top-level window under a screen position (or None)."""
    hwnd = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    return user32.GetAncestor(hwnd, GA_ROOT) if hwnd else None