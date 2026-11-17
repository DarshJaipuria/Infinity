import ctypes
import keyword
import os
import re
import time
import tkinter as tk


class TypingAborted(Exception):
    pass


def _esc_pressed():
    """Global Esc check (works even if the editor window is not focused)."""
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000)
    except Exception:
        return False


# =====================================================================
#  Simple one-shot editor: types ready-made code (used by save_file)
# =====================================================================
def type_into_editor(path, code, delay=0.01, hold=2.0):
    """Show an editor window, type `code` into it live, then save it to `path`."""
    code = code.replace("\r\n", "\n")
    name = os.path.basename(path)

    root = tk.Tk()
    root.title(f"Infinity Editor - {name}")
    width, height = 900, 600
    x = (root.winfo_screenwidth() - width) // 2
    y = (root.winfo_screenheight() - height) // 2
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.configure(bg="#1e1e1e")
    root.attributes("-topmost", True)

    tk.Label(root, text=path, anchor="w", bg="#252526", fg="#9cdcfe",
             font=("Consolas", 10), padx=10, pady=6).pack(fill="x")
    text = tk.Text(root, bg="#1e1e1e", fg="#d4d4d4", insertbackground="#ffffff",
                   font=("Consolas", 12), wrap="none", padx=10, pady=10, borderwidth=0)
    text.pack(fill="both", expand=True)
    status = tk.Label(root, text="Typing...  (press Esc to stop)", anchor="w",
                      bg="#007acc", fg="white", font=("Segoe UI", 9), padx=10, pady=3)
    status.pack(fill="x")

    stop = {"flag": False}
    root.bind("<Escape>", lambda e: stop.update(flag=True))
    root.protocol("WM_DELETE_WINDOW", lambda: stop.update(flag=True))
    root.update()
    root.focus_force()

    try:
        open(path, "w", encoding="utf-8").close()
        for ch in code:
            if stop["flag"] or _esc_pressed():
                raise TypingAborted("stopped by user")
            text.insert("end", ch)
            text.see("end")
            root.update()
            time.sleep(delay)

        content = text.get("1.0", "end-1c")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        status.config(text=f"Saved ✔  {path}", bg="#2e7d32")
        root.update()
        end = time.time() + hold
        while time.time() < end:
            root.update()
            time.sleep(0.05)
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


# =====================================================================
#  Live editor: shows code as the model writes it, with colors
# =====================================================================
_TOKEN = re.compile(
    r'(?P<comment>#[^\n]*)'
    r'|(?P<string>"""[\s\S]*?(?:"""|\Z)|\'\'\'[\s\S]*?(?:\'\'\'|\Z)|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\')'
    r'|(?P<number>\b\d+(?:\.\d+)?\b)'
    r'|(?P<name>[A-Za-z_]\w*)'
)
_BUILTINS = {
    "print", "len", "range", "int", "str", "float", "list", "dict", "set", "tuple", "open", "min", "max",
    "sum", "abs", "enumerate", "zip", "map", "filter", "sorted", "isinstance", "super", "bool", "round",
    "input", "reversed", "any", "all", "type",
}
_COLORS = {
    "keyword": "#c586c0", "string": "#ce9178", "comment": "#6a9955", "number": "#b5cea8",
    "defname": "#dcdcaa", "builtin": "#4ec9b0", "self": "#9cdcfe",
}


class LiveEditor:
    """A code window that stays open while Infinity plans, writes, tests and fixes a program."""

    def __init__(self, title="Infinity Editor"):
        self.stop = False
        self._last_tag = 0.0
        self.root = tk.Tk()
        r = self.root
        r.title(title)
        width, height = 980, 680
        x = (r.winfo_screenwidth() - width) // 2
        y = (r.winfo_screenheight() - height) // 2
        r.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")
        r.configure(bg="#1e1e1e")
        r.attributes("-topmost", True)

        self.header = tk.Label(r, text="(new file)", anchor="w", bg="#252526", fg="#9cdcfe",
                               font=("Consolas", 10), padx=10, pady=6)
        self.header.pack(fill="x")
        frame = tk.Frame(r, bg="#1e1e1e")
        frame.pack(fill="both", expand=True)
        self.text = tk.Text(frame, bg="#1e1e1e", fg="#d4d4d4", insertbackground="#ffffff",
                            font=("Consolas", 12), wrap="none", padx=10, pady=10, borderwidth=0)
        self.text.pack(fill="both", expand=True)
        for tag, color in _COLORS.items():
            self.text.tag_configure(tag, foreground=color)
        self.bar = tk.Label(r, text="", anchor="w", bg="#007acc", fg="white",
                            font=("Segoe UI", 9), padx=10, pady=3)
        self.bar.pack(fill="x")

        r.bind("<Escape>", lambda e: setattr(self, "stop", True))
        r.protocol("WM_DELETE_WINDOW", lambda: setattr(self, "stop", True))
        r.update()
        r.focus_force()

    # ----- state -----
    def set_path(self, path):
        self.header.config(text=path)

    def status(self, text, color="#007acc"):
        self.bar.config(text=f"{text}   (press Esc to stop)", bg=color)
        self.pump()

    def pump(self):
        """Keep the window alive. Raises TypingAborted if the user pressed Esc or closed it."""
        if self.stop or _esc_pressed():
            raise TypingAborted("stopped by user")
        try:
            self.root.update()
        except tk.TclError:
            raise TypingAborted("the editor window was closed")

    def hide(self):
        self.root.withdraw()

    def show(self):
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.update()

    # ----- text -----
    def clear(self):
        self.text.delete("1.0", "end")
        self.pump()

    def line_count(self):
        return int(self.text.index("end-1c").split(".")[0])

    def append(self, piece):
        self.text.insert("end", piece)
        self.text.see("end")
        if "\n" in piece and time.time() - self._last_tag > 0.6:
            self.retag()
        self.pump()

    def set_text(self, code):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", code)
        self.retag()
        self.text.see("1.0")
        self.pump()

    def retag(self):
        self._last_tag = time.time()
        content = self.text.get("1.0", "end-1c")
        for tag in _COLORS:
            self.text.tag_remove(tag, "1.0", "end")
        after_def = False
        for m in _TOKEN.finditer(content):
            kind = m.lastgroup
            word = m.group()
            tag = None
            if kind in ("comment", "string", "number"):
                tag = kind
            else:
                if after_def:
                    tag, after_def = "defname", False
                elif keyword.iskeyword(word):
                    tag = "keyword"
                    after_def = word in ("def", "class")
                elif word == "self":
                    tag = "self"
                elif word in _BUILTINS:
                    tag = "builtin"
            if tag:
                self.text.tag_add(tag, f"1.0+{m.start()}c", f"1.0+{m.end()}c")

    # ----- end -----
    def finish(self, message, hold=2.0):
        self.status(message, "#2e7d32")
        end = time.time() + hold
        while time.time() < end:
            self.pump()
            time.sleep(0.05)

    def close(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
