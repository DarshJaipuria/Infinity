import ctypes
import threading
import time

# Make coordinates match real screen pixels on 125% / 150% scaled displays
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

KILL = threading.Event()


def _watch_esc():
    """Background thread: any press of Esc raises the kill flag."""
    try:
        user32 = ctypes.windll.user32
    except Exception:
        return
    while True:
        try:
            if user32.GetAsyncKeyState(0x1B) & 0x8000:
                KILL.set()
        except Exception:
            pass
        time.sleep(0.02)


threading.Thread(target=_watch_esc, daemon=True).start()


def killed():
    return KILL.is_set()


def clear_kill():
    KILL.clear()
