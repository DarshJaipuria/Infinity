"""Auto-play test for tkinter programs.

Usage:  python tk_smoke.py game.py [seconds]

Runs the program, replaces mainloop() with a random "monkey" player (key presses, button
clicks, canvas clicks) for a few seconds, and prints a JSON report between two markers.
Dialogs are answered automatically so nothing blocks.
"""
import hashlib
import json
import os
import random
import runpy
import sys
import threading
import time
import traceback
from collections import Counter

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 6.0
REPORT = {
    "opened_window": False, "seconds": 0.0, "actions": {}, "dialogs": [],
    "errors": [], "ui_changed": None, "states_seen": 0,
}
START, END = "@@REPORT_START@@", "@@REPORT_END@@"


def emit():
    REPORT["ok"] = bool(REPORT["opened_window"]) and not REPORT["errors"]
    print(START + json.dumps(REPORT) + END, flush=True)


# ---------- dialogs answer themselves ----------
def _dialog(name, result):
    def fake(*args, **kwargs):
        text = str(args[1]) if len(args) > 1 else str(kwargs.get("message", ""))
        REPORT["dialogs"].append(f"{name}: {text[:60]}")
        return result
    return fake


for _n in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, _n, _dialog(_n, "ok"))
for _n in ("askyesno", "askokcancel", "askretrycancel"):
    setattr(messagebox, _n, _dialog(_n, True))
messagebox.askquestion = _dialog("askquestion", "yes")
messagebox.askyesnocancel = _dialog("askyesnocancel", True)
simpledialog.askstring = _dialog("askstring", "Tester")
simpledialog.askinteger = _dialog("askinteger", 1)
simpledialog.askfloat = _dialog("askfloat", 1.0)
for _n in ("askopenfilename", "asksaveasfilename", "askdirectory"):
    setattr(filedialog, _n, _dialog(_n, ""))
tk.Misc.wait_window = lambda self, window=None: None


# ---------- errors inside callbacks (key handlers, after() loops, buttons) ----------
def _report_exc(self, exc, val, tb):
    text = "".join(traceback.format_exception(exc, val, tb))
    if text not in REPORT["errors"] and len(REPORT["errors"]) < 3:
        REPORT["errors"].append(text[-1800:])


tk.Misc.report_callback_exception = _report_exc
tk.Tk.report_callback_exception = _report_exc


# ---------- looking at the screen state ----------
def _widgets(w):
    out = [w]
    for child in w.winfo_children():
        out += _widgets(child)
    return out


def _signature(root):
    rows = []
    for w in _widgets(root):
        try:
            cls = w.winfo_class()
            row = [cls]
            if cls == "Canvas":
                items = w.find_all()
                row.append(len(items))
                for item in items[-400:]:       # the newest items are the moving ones
                    kind = w.type(item)
                    extra = w.itemcget(item, "text") if kind == "text" else (
                        w.itemcget(item, "fill") if kind != "image" else "")
                    row.append((kind, tuple(round(c) for c in w.coords(item)), extra))
            else:
                for opt in ("text", "bg", "state"):
                    try:
                        row.append(str(w.cget(opt)))
                    except tk.TclError:
                        pass
            rows.append(row)
        except tk.TclError:
            pass
    return hashlib.md5(repr(rows).encode()).hexdigest()


KEYS = ["Up", "Down", "Left", "Right", "w", "a", "s", "d", "space", "Return", "r", "p", "1", "2", "3"]


def _press(root, stats):
    try:
        target = root.focus_get() or root
    except (KeyError, tk.TclError):
        target = root
    key = random.choice(KEYS)
    target.event_generate("<KeyPress>", keysym=key)
    target.event_generate("<KeyRelease>", keysym=key)
    stats["key"] += 1


def _click(root, stats):
    widgets = [w for w in _widgets(root) if w.winfo_ismapped()]
    buttons = [w for w in widgets if w.winfo_class() in ("Button", "TButton", "Checkbutton", "Radiobutton", "TCheckbutton", "TRadiobutton")]
    others = [w for w in widgets if w.winfo_class() in ("Canvas", "Frame", "Label", "TFrame", "TLabel") and w.winfo_width() > 4]
    if buttons and (not others or random.random() < 0.6):
        b = random.choice(buttons)
        try:
            if str(b.cget("state")) != "disabled":
                b.invoke()
                stats["button"] += 1
        except tk.TclError:
            pass
    elif others:
        w = random.choice(others)
        x, y = random.randint(1, max(1, w.winfo_width() - 2)), random.randint(1, max(1, w.winfo_height() - 2))
        w.event_generate("<Motion>", x=x, y=y)
        w.event_generate("<Button-1>", x=x, y=y)
        w.event_generate("<ButtonRelease-1>", x=x, y=y)
        stats["click"] += 1


def play(root, seconds):
    random.seed(42)
    stats = Counter()
    seen = set()
    try:
        root.update()
        root.focus_force()
        seen.add(_signature(root))
    except tk.TclError:
        return stats, seen
    end = time.time() + seconds
    next_action = 0.0
    while time.time() < end:
        try:
            root.update()
        except tk.TclError:
            break
        now = time.time()
        if now >= next_action:
            next_action = now + random.uniform(0.03, 0.12)
            roll = random.random()
            try:
                if roll < 0.55:
                    _press(root, stats)
                elif roll < 0.9:
                    _click(root, stats)
                seen.add(_signature(root))
            except tk.TclError:
                break
        time.sleep(0.005)
    return stats, seen


def _mainloop(self, n=0):
    REPORT["opened_window"] = True
    t0 = time.time()
    stats, seen = play(self, SECONDS)
    REPORT["seconds"] = round(time.time() - t0, 1)
    REPORT["actions"] = dict(stats)
    REPORT["states_seen"] = len(seen)
    REPORT["ui_changed"] = len(seen) > 1
    try:
        self.destroy()
    except tk.TclError:
        pass


tk.Misc.mainloop = _mainloop
tk.mainloop = lambda n=0: _mainloop(tk._default_root, n) if tk._default_root else None


def _watchdog():
    time.sleep(SECONDS + 15)
    REPORT["errors"].append("The program did not finish in time (a blocking loop, or a dialog waiting for input).")
    emit()
    os._exit(2)


def main():
    path = os.path.abspath(sys.argv[1])
    os.chdir(os.path.dirname(path))
    sys.path.insert(0, os.getcwd())
    sys.argv = [path]
    threading.Thread(target=_watchdog, daemon=True).start()
    try:
        runpy.run_path(path, run_name="__main__")
    except SystemExit:
        pass
    except BaseException:
        REPORT["errors"].append("Crash: " + traceback.format_exc()[-1800:])
    if not REPORT["opened_window"] and not REPORT["errors"]:
        REPORT["errors"].append("The program ended without opening a window (mainloop was never reached).")
    emit()


if __name__ == "__main__":
    main()
