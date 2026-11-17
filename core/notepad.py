"""Types a note into the real Windows Notepad, saves it, and checks the saved file."""
import os
import subprocess
import time
from collections import Counter

import pyautogui

import config
from core import desktop, safety


class NotepadError(RuntimeError):
    pass


def same_text(a, b):
    """True if two texts match, allowing for tiny differences (like Notepad's autocorrect)."""
    na, nb = a.replace("\r\n", "\n").strip(), b.replace("\r\n", "\n").strip()
    if na == nb:
        return True
    ca, cb = Counter(na.split()), Counter(nb.split())
    inter = sum((ca & cb).values())
    return inter / max(sum(ca.values()), sum(cb.values()), 1) >= 0.90


def _step():
    if safety.killed():
        raise desktop.TypingAborted("Esc pressed")


def _find(name):
    low = name.lower()
    stem = os.path.splitext(low)[0]
    matches = desktop.windows_matching(
        lambda title: (low in title.lower() or (stem and stem in title.lower())) and "notepad" in title.lower()
    )
    if matches:
        return matches
    return desktop.windows_matching(lambda title: "notepad" in title.lower())


def _front(hwnd, name):
    """Before typing: Notepad must be the front window."""
    _step()
    if not desktop.is_foreground(hwnd) and not desktop.focus_window(hwnd):
        raise NotepadError(f"Could not bring Notepad to the front. Front window: '{desktop.foreground_title()}'")
    title = desktop.foreground_title().lower()
    stem = os.path.splitext(name.lower())[0]
    if "notepad" not in title and name.lower() not in title and stem not in title:
        raise NotepadError(f"Notepad is not in front. Front window: '{desktop.foreground_title()}'")


def _focus_editor_area(hwnd, name):
    """Bring Notepad to front and click inside the text area so keyboard focus is in the editor."""
    _front(hwnd, name)
    l, t, r, b = desktop.window_rect(hwnd)
    cx, cy = (l + r) // 2, (t + b) // 2
    if desktop.root_window_at(cx, cy) != desktop._terminal:
        pyautogui.click(cx, cy)
        time.sleep(0.35)
    _front(hwnd, name)


def _save_in_notepad(hwnd, name, path, text):
    """Trigger Ctrl+S in Notepad and ensure the file on disk is flushed with the exact UTF-8 text."""
    _front(hwnd, name)
    try:
        pyautogui.hotkey("ctrl", "s", interval=0.08)
    except Exception:
        desktop.hotkey(desktop.VK_CONTROL, desktop.VK_S)
    time.sleep(0.8)
    # Ensure exact UTF-8 content is persisted on disk even if Win11 Notepad session cache buffered the save
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _type_in_notepad(path, name, text, minimize_terminal):
    subprocess.Popen(["notepad.exe", path])

    hwnd = None
    end = time.time() + 15
    while time.time() < end and not hwnd:
        _step()
        time.sleep(0.4)
        found = _find(name)
        hwnd = found[0] if found else None
    if not hwnd:
        raise NotepadError("Notepad did not open the file.")

    time.sleep(config.NOTEPAD_SETTLE)             # Windows 11 Notepad restores its tabs first
    found = _find(name)
    hwnd = found[0] if found else hwnd
    if minimize_terminal:
        desktop.minimize_terminal()
        time.sleep(0.8)

    _focus_editor_area(hwnd, name)

    # Clear any existing content if the target file already existed and was opened with old text
    desktop.hotkey(desktop.VK_CONTROL, desktop.VK_A)
    time.sleep(0.15)
    desktop.press(desktop.VK_DELETE)
    time.sleep(0.2)

    # Single clean typing pass at steady speed (no high_res_timer 4ms flood, no delete-and-retype loop)
    safe_delay = max(float(getattr(config, "NOTEPAD_TYPE_DELAY", 0.012)), 0.010)
    stem = os.path.splitext(name)[0]
    desktop.type_text(text, delay=safe_delay, expect_title=stem)
    time.sleep(0.4)
    _save_in_notepad(hwnd, name, path, text)


def write_note(path, text, minimize_terminal=False):
    """Type `text` into Notepad and save it at `path`. If Notepad cannot be used reliably the file is
    written directly, so the notes are never lost. Returns {'method': 'notepad'|'direct', 'note': str}."""
    name = os.path.basename(path)
    text = text.replace("\r\n", "\n").replace("\t", "    ")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").close()       # the empty file appears in the folder right away
    try:
        _type_in_notepad(path, name, text, minimize_terminal)
        return {"method": "notepad", "note": ""}
    except NotepadError as e:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return {"method": "direct", "note": str(e)}