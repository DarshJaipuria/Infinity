"""Infinity Glass GUI - frameless, translucent, always-on-top PyQt6 overlay.

Public API (used by main.py):
    available()            -> (ok: bool, reason: str)
    run(agent, commands)   -> process exit code; raises GlassUnavailable if the
                              GUI cannot be initialised (caller falls back to CLI)
"""
import ctypes
import html
import math
import os
import queue
import re
import sys
import threading
import time

os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.window=false")

# Fix Windows DLL conflict: prevent Anaconda's icuuc.dll from shadowing Windows System32 icuuc.dll
if sys.platform == "win32":
    try:
        sys32 = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32")
        for _dll in ("icuuc.dll", "icuin.dll", "icu.dll"):
            _p = os.path.join(sys32, _dll)
            if os.path.isfile(_p):
                ctypes.CDLL(_p)
    except Exception:
        pass

    try:
        import site
        for _sp in site.getsitepackages():
            _qbin = os.path.join(_sp, "PyQt6", "Qt6", "bin")
            if os.path.isdir(_qbin) and hasattr(os, "add_dll_directory"):
                os.add_dll_directory(_qbin)
    except Exception:
        pass


class GlassUnavailable(RuntimeError):
    pass


try:
    from PyQt6.QtCore import (QEasingCurve, QObject, QPointF, QRectF, Qt, QTimer,
                              QVariantAnimation, pyqtSignal)
    from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter,
                             QPainterPath, QPen, QRadialGradient)
    from PyQt6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel,
                                 QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                                 QSizeGrip, QSizePolicy, QVBoxLayout, QWidget)
    _QT_ERROR = None
except Exception as _e:  # PyQt6 missing or broken
    _QT_ERROR = _e
    QWidget = QObject = QPlainTextEdit = QFrame = QScrollArea = QLabel = QPushButton = object
    pyqtSignal = lambda *a, **k: None

# ----------------------------------------------------------------- palette
BASE_TINT = "#101935"
BORDER = "#335c9c"
CYAN = "#22d3ee"
CYAN_CORE = "#06b6d4"
CYAN_GLOW = "#67e8f9"
ACCENT_VIOLET = "#a78bfa"
RING_A = "#2563eb"
RING_B = "#7c3aed"
BRACKET = "#38bdf8"
CORE_FILL = "#09122b"
TXT = "#e2e8f0"
MUTED = "#94a3b8"

HUD_PALETTES = {
    "idle": {
        "primary": "#67e8f9",
        "core": "#22d3ee",
        "glow": "#ecfeff",
        "ring_a": "#38bdf8",
        "ring_b": "#a5f3fc",
        "bracket": "#7dd3fc",
        "core_fill": "#040817",
    },
    "working": {
        "primary": "#fb7185",
        "core": "#f43f5e",
        "glow": "#fda4af",
        "ring_a": "#9f1239",
        "ring_b": "#e11d48",
        "bracket": "#f43f5e",
        "core_fill": "#260711",
    },
    "generating": {
        "primary": "#fbbf24",
        "core": "#f59e0b",
        "glow": "#fde68a",
        "ring_a": "#92400e",
        "ring_b": "#d97706",
        "bracket": "#fbbf24",
        "core_fill": "#211504",
    },
}

IDLE_OPACITY = 0.86
WORK_OPACITY = 0.52
MIN_OPACITY = 0.25
BUSY_SPEED = 2.4
GEN_SPEED = 1.6
BASE_W = 533.0
BASE_H = 734.0
HUD_HEIGHT = 118
CLOCK_PT = 26  # time font size (pt) at base scale
EDGE = 6  # native resize border (px)

# Intro sequence timing (seconds) & screen coverage ratios matching reference screenshots
INTRO_LOAD_SEC = 4.4
INTRO_SHRINK_SEC = 1.10
LAUNCH_W_RATIO = 0.462
LAUNCH_H_RATIO = 0.936
FINAL_W_RATIO = 0.278
FINAL_H_RATIO = 0.680


class AgentStopped(BaseException):
    """Injected into the worker thread by Stop. BaseException so tools' `except Exception` can't swallow it."""


def available():
    if _QT_ERROR is not None:
        return False, f"PyQt6 not available ({_QT_ERROR})"
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
                                                  or os.environ.get("QT_QPA_PLATFORM")):
        return False, "no display environment"
    return True, ""


# ----------------------------------------------------------------- markdown -> Qt rich text
_CODE_BG, _CODE_FG = "#091024", "#d8e6ff"


def _inline(text):
    codes = []

    def stash(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`\n]+)`", stash, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = re.sub(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<![_\w])_(?!\s)(.+?)(?<!\s)_(?![_\w])", r"<i>\1</i>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                  lambda m: f'<a href="{m.group(2)}" style="color:{CYAN}">{m.group(1)}</a>', text)

    def _format_code(m):
        raw = codes[int(m.group(1))]
        escaped = html.escape(raw, quote=False)
        breakable = re.sub(r"([\\/._-])", r"\1&#8203;", escaped)
        return (
            f'<code style="background-color:#112244; color:#67e8f9; '
            f'font-family:Consolas,monospace; padding:1px 4px; border-radius:3px;">{breakable}</code>'
        )

    text = re.sub(r"\x00(\d+)\x00", _format_code, text)
    return text


def _code_block(code, lang, scale=1.0):
    lbl_pt = round(11.0 * scale, 1)
    body_pt = round(11.5 * scale, 1)
    label = (f'<span style="color:{ACCENT_VIOLET}; font-size:{lbl_pt}pt; font-family:Consolas,monospace;">'
             f'{html.escape(lang)}</span><br>') if lang else ""
    body = html.escape(code.rstrip("\n"), quote=False).replace(" ", "&nbsp;").replace("\n", "<br>")
    return (f'<table width="100%" cellspacing="0" cellpadding="8" bgcolor="{_CODE_BG}" '
            f'style="margin:4px 0; background-color:{_CODE_BG}; border-radius:6px;"><tr><td bgcolor="{_CODE_BG}">{label}'
            f'<span style="color:{_CODE_FG}; font-family:Consolas,monospace; font-size:{body_pt}pt;">{body}</span>'
            f'</td></tr></table>')


def _render_md_table(table_lines, scale=1.0):
    rows = []
    for raw in table_lines:
        stripped = raw.strip().strip("|")
        cells = [c.strip() for c in stripped.split("|")]
        if all(re.match(r"^:?-{2,}:?$", c) for c in cells if c):
            continue
        rows.append(cells)
    if not rows:
        return ""
    cell_pt = round(11.5 * scale, 1)
    html_rows = []
    for r_idx, row in enumerate(rows):
        bg = "#132347" if r_idx == 0 else ("#0b1530" if r_idx % 2 == 1 else "#0e1b3a")
        col_html = []
        for c in row:
            content = f"<b>{_inline(c)}</b>" if r_idx == 0 else _inline(c)
            col_html.append(
                f'<td bgcolor="{bg}" style="padding:5px 8px; color:{TXT}; font-size:{cell_pt}pt;">{content}</td>'
            )
        html_rows.append("<tr>" + "".join(col_html) + "</tr>")
    return (
        f'<table width="100%" cellspacing="1" cellpadding="4" bgcolor="{BORDER}" '
        f'style="margin:6px 0;">{"".join(html_rows)}</table>'
    )


def md_to_html(md, scale=1.0):
    out, lines, i = [], md.replace("\r\n", "\n").split("\n"), 0
    list_kind = None

    def close_list():
        nonlocal list_kind
        if list_kind:
            out.append(f"</{list_kind}>")
            list_kind = None

    while i < len(lines):
        line = lines[i]
        fence = re.match(r"^\s*```\s*([\w+#.-]*)\s*$", line)
        if fence:
            close_list()
            buf, i = [], i + 1
            while i < len(lines) and not re.match(r"^\s*```\s*$", lines[i]):
                buf.append(lines[i])
                i += 1
            out.append(_code_block("\n".join(buf), fence.group(1), scale=scale))
            i += 1
            continue
        if "|" in line and re.match(r"^\s*\|.*\|\s*$", line):
            close_list()
            tbl_buf = []
            while i < len(lines) and "|" in lines[i] and re.match(r"^\s*\|.*\|\s*$", lines[i]):
                tbl_buf.append(lines[i])
                i += 1
            out.append(_render_md_table(tbl_buf, scale=scale))
            continue
        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        ul = re.match(r"^\s*(?:[-*+•]|\u2022)\s+(.*)$", line)
        ol = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        bq = re.match(r"^\s*>\s?(.*)$", line)
        if h:
            close_list()
            lvl = len(h.group(1))
            size = round({1: 18.5, 2: 16.5, 3: 14.5}.get(lvl, 13.5) * scale, 1)
            out.append(f'<p style="margin:6px 0 3px 0; color:{CYAN_GLOW}; font-size:{size}pt; '
                       f'font-weight:600;">{_inline(h.group(2))}</p>')
        elif ul or ol:
            kind = "ul" if ul else "ol"
            if list_kind != kind:
                close_list()
                out.append(f'<{kind} style="margin:3px 0 3px -12px;">')
                list_kind = kind
            out.append(f'<li style="margin:2px 0; text-align:left;">{_inline((ul or ol).group(1))}</li>')
        elif re.match(r"^\s*([-*_])\s*\1\s*\1[\s\1]*$", line):
            close_list()
            out.append(f'<hr style="color:{BORDER};">')
        elif bq:
            close_list()
            out.append(f'<p style="margin:2px 0 2px 10px; color:{MUTED}; text-align:left;">&#9475; {_inline(bq.group(1))}</p>')
        elif not line.strip():
            close_list()
        else:
            close_list()
            out.append(f'<p style="margin:3px 0; text-align:left;">{_inline(line)}</p>')
        i += 1
    close_list()
    return "".join(out)


# ----------------------------------------------------------------- Windows glass effects
def _apply_blur(hwnd):
    """Acrylic blur-behind via SetWindowCompositionAttribute (Win10/11). Returns (blur_ok, rounded)."""
    if not sys.platform.startswith("win"):
        return False, False
    try:
        class ACCENT(ctypes.Structure):
            _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int),
                        ("color", ctypes.c_uint), ("anim", ctypes.c_int)]

        class WCA(ctypes.Structure):
            _fields_ = [("attr", ctypes.c_int), ("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]

        fn = ctypes.windll.user32.SetWindowCompositionAttribute
        fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(WCA)]
        fn.restype = ctypes.c_int
        ok = False
        for state, color in ((4, 0xCC101935), (3, 0)):   # acrylic blur first, plain blur fallback
            accent = ACCENT(state, 0, color, 0)
            data = WCA(19, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p), ctypes.sizeof(accent))
            if fn(ctypes.c_void_p(int(hwnd)), ctypes.byref(data)):
                ok = True
                break
        if not ok:
            return False, False
        rounded = False
        try:   # Win11: round the corners so the blur is clipped too
            if sys.getwindowsversion().build >= 22000:
                dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
                dwm.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
                v = ctypes.c_int(2)
                rounded = dwm(ctypes.c_void_p(int(hwnd)), 33, ctypes.byref(v), ctypes.sizeof(v)) == 0
        except Exception:
            pass
        return True, rounded
    except Exception:
        return False, False


def _user32():
    u = ctypes.windll.user32
    u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
    return u


def set_click_through(hwnd, on):
    """Let mouse clicks pass through the window to whatever is underneath it."""
    if not sys.platform.startswith("win"):
        return
    try:
        u, h = _user32(), ctypes.c_void_p(int(hwnd))
        style = u.GetWindowLongPtrW(h, -20)                    # GWL_EXSTYLE
        style = (style | 0x20) if on else (style & ~0x20)      # WS_EX_TRANSPARENT
        u.SetWindowLongPtrW(h, -20, style)
    except Exception:
        pass


# ----------------------------------------------------------------- animated HUD
def _lerp_color(cur, target, t):
    return QColor(
        round(cur.red() + (target.red() - cur.red()) * t),
        round(cur.green() + (target.green() - cur.green()) * t),
        round(cur.blue() + (target.blue() - cur.blue()) * t),
    )


class HudWidget(QWidget):
    ORBIT_RADIUS = 0.72
    DOT_COUNT = 3
    DOT_STEP = 2.0 * math.pi / DOT_COUNT

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(HUD_HEIGHT, HUD_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.busy = False
        self.state = "idle"                   # "idle" | "working" | "generating"
        self.alpha = 1.0
        self._speed = 1.0
        self._rot = [0.0, 0.0, 0.0]           # outer, middle, inner (degrees)
        self._orbit_angle = 0.0               # single shared angle (radians)
        self._pulse_t = 0.0
        self._wave_t = 0.0                    # expanding shockwave phase for working state
        self._work_blend = 0.0                # 0..1 smooth blend for working-only animations
        self._colors = {k: QColor(v) for k, v in HUD_PALETTES["idle"].items()}
        self._last = time.perf_counter()
        self._on_tick_cb = None
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    @staticmethod
    def _dash_pen(color, pattern, width=1.6):
        p = QPen(color, width)
        p.setDashPattern([float(x) for x in pattern])
        p.setCapStyle(Qt.PenCapStyle.FlatCap)
        return p

    def set_state(self, state):
        if state not in HUD_PALETTES:
            state = "idle"
        self.state = state
        self.busy = state != "idle"

    def set_busy(self, busy):
        self.set_state("working" if busy else "idle")

    def pause(self, paused):
        if paused:
            self._timer.stop()
        elif not self._timer.isActive():
            self._last = time.perf_counter()
            self._timer.start()

    def _tick(self):
        now = time.perf_counter()
        dt = min(now - self._last, 0.05)
        self._last = now

        if self.state == "working":
            target_speed = BUSY_SPEED
            pulse_rate = 6.2
        elif self.state == "generating":
            target_speed = GEN_SPEED
            pulse_rate = 3.8
        else:
            target_speed = 1.0
            pulse_rate = 2.4

        self._speed += (target_speed - self._speed) * min(1.0, dt * 6.0)
        f = dt * 60.0 * self._speed
        self._rot[0] = (self._rot[0] + 0.5 * f) % 360
        self._rot[1] = (self._rot[1] - 0.8 * f) % 360
        self._rot[2] = (self._rot[2] + 1.1 * f) % 360

        # All 3 dots rotate together on the same circular loop, equidistant, same direction & speed
        self._orbit_angle = (self._orbit_angle + 1.8 * dt * self._speed) % (2.0 * math.pi)
        self._pulse_t += dt * pulse_rate
        self._wave_t = (self._wave_t + dt * 1.15) % 1.0

        work_target = 1.0 if self.state == "working" else 0.0
        self._work_blend += (work_target - self._work_blend) * min(1.0, dt * 6.5)

        palette = HUD_PALETTES[self.state]
        color_t = min(1.0, dt * 8.0)
        for key, hex_val in palette.items():
            self._colors[key] = _lerp_color(self._colors[key], QColor(hex_val), color_t)

        if self._on_tick_cb is not None:
            self._on_tick_cb()
        self.update()

    def _geom(self):
        w, h = self.width(), self.height()
        side = min(w, h)
        scale = side / float(HUD_HEIGHT)
        R = max(16.0, side / 2.0 - 10.0 * scale)
        return w / 2.0, h / 2.0, R

    def paint_hud_at(self, p: QPainter, cx: float, cy: float, R: float, boost_blend: float = 0.0):
        """Render the animated HUD radar at arbitrary center (cx, cy) and radius R."""
        k = R / 46.0
        c = QPointF(cx, cy)

        primary = self._colors["primary"]
        core_col = self._colors["core"]
        glow_col = self._colors["glow"]
        ring_a = self._colors["ring_a"]
        ring_b = self._colors["ring_b"]
        core_fill = self._colors["core_fill"]

        work_blend = max(self._work_blend, boost_blend)

        # Soft outer ambient aura when zoomed in
        if boost_blend > 0.01:
            aura_r = R * 1.24
            aura = QRadialGradient(c, aura_r)
            aura.setColorAt(0.0, QColor(primary.red(), primary.green(), primary.blue(), int(64 * boost_blend)))
            aura.setColorAt(0.65, QColor(124, 58, 237, int(36 * boost_blend)))
            aura.setColorAt(1.0, QColor(16, 25, 53, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(aura))
            p.drawEllipse(c, aura_r, aura_r)

        # rotating dashed rings
        ring_specs = (
            (ring_a, [3, 5], 0.96, self._rot[0]),
            (ring_b, [7, 5], 0.80, self._rot[1]),
            (ring_a, [13, 6], 0.64, self._rot[2]),
        )
        for col, pat, rr, rot in ring_specs:
            p.save()
            p.translate(c)
            p.rotate(rot)
            p.setPen(self._dash_pen(col, pat, width=1.4 * k))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(0, 0), R * rr, R * rr)
            p.restore()

        # expanding radar shockwaves
        if work_blend > 0.02:
            for offset in (0.0, 0.5):
                phase = (self._wave_t + offset) % 1.0
                wave_r = R * (0.46 + 0.58 * phase)
                wave_alpha = int(175 * (1.0 - phase) * work_blend)
                wave_col = QColor(primary.red(), primary.green(), primary.blue(), wave_alpha)
                p.setPen(QPen(wave_col, 1.6 * k * (1.0 - 0.5 * phase)))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, wave_r, wave_r)

        # radar core
        rc = R * 0.46
        p.setBrush(QBrush(core_fill))
        p.setPen(QPen(primary, 1.2 * k))
        p.drawEllipse(c, rc, rc)
        spoke = QColor(primary)
        spoke.setAlpha(48)
        p.setPen(QPen(spoke, 1.0 * k))
        for idx in range(6):
            a = math.radians(idx * 60)
            p.drawLine(c, QPointF(cx + rc * math.cos(a), cy + rc * math.sin(a)))

        # rotating core scanner arc
        if work_blend > 0.02:
            arc_col = QColor(glow_col.red(), glow_col.green(), glow_col.blue(), int(180 * work_blend))
            p.setPen(QPen(arc_col, 2.0 * k, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            arc_r = rc * 0.78
            arc_rect = QRectF(cx - arc_r, cy - arc_r, arc_r * 2.0, arc_r * 2.0)
            start_deg = -math.degrees(self._orbit_angle * 1.5)
            p.drawArc(arc_rect, int(start_deg * 16), int(95 * 16))
            p.drawArc(arc_rect, int((start_deg + 180) * 16), int(95 * 16))

        # 3 equidistant orbiting dots on the same circular loop, same direction & speed
        orbit_r = R * self.ORBIT_RADIUS
        orbit_rect = QRectF(cx - orbit_r, cy - orbit_r, orbit_r * 2.0, orbit_r * 2.0)
        halo_r = 7.0 * k
        dot_r = 2.6 * k
        for i in range(self.DOT_COUNT):
            ang = self._orbit_angle + i * self.DOT_STEP

            if work_blend > 0.02:
                trail_col = QColor(primary.red(), primary.green(), primary.blue(), int(130 * work_blend))
                p.setPen(QPen(trail_col, 2.0 * k, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.setBrush(Qt.BrushStyle.NoBrush)
                head_deg = -math.degrees(ang)
                p.drawArc(orbit_rect, int(head_deg * 16), int(28 * 16))

            pt = QPointF(cx + orbit_r * math.cos(ang), cy + orbit_r * math.sin(ang))
            g = QRadialGradient(pt, halo_r)
            g.setColorAt(0.0, QColor(primary.red(), primary.green(), primary.blue(), 175))
            g.setColorAt(1.0, QColor(primary.red(), primary.green(), primary.blue(), 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g))
            p.drawEllipse(pt, halo_r, halo_r)
            p.setBrush(QBrush(primary))
            p.drawEllipse(pt, dot_r, dot_r)

        # pulsing centre (zoom in / out)
        base = R * 0.12
        amp = 0.28 if (self.state == "working" or boost_blend > 0.2) else 0.22
        rad = base * (1.0 + amp * math.sin(self._pulse_t))
        g = QRadialGradient(c, rad * 2.4)
        g.setColorAt(0.0, QColor(glow_col.red(), glow_col.green(), glow_col.blue(), 155))
        g.setColorAt(1.0, QColor(glow_col.red(), glow_col.green(), glow_col.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(c, rad * 2.4, rad * 2.4)
        p.setPen(QPen(glow_col, 1.1 * k))
        p.setBrush(QBrush(core_col))
        p.drawEllipse(c, rad, rad)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self.alpha)
        cx, cy, R = self._geom()
        self.paint_hud_at(p, cx, cy, R)
        p.end()


# ----------------------------------------------------------------- full-zoom startup intro overlay
class IntroOverlay(QWidget):
    """Full-zoom HUD startup animation in a large centered dialog box with a 4.4s loading bar.
    As the HUD animation shrinks and glides to the top-left slot, the dialog box itself smoothly
    shortens around the screen center to its post-launch size."""

    finished = pyqtSignal()

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self._t0 = time.perf_counter()
        self._done = False
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def start(self):
        self._t0 = time.perf_counter()
        self._done = False
        self.win.hud._on_tick_cb = self._on_hud_tick
        self.show()
        self.update()

    def _on_hud_tick(self):
        if self._done:
            return
        elapsed = time.perf_counter() - self._t0
        if elapsed > INTRO_LOAD_SEC:
            shrink_u = self._smoothstep((elapsed - INTRO_LOAD_SEC) / INTRO_SHRINK_SEC)
            self.win._apply_intro_window_shrink(shrink_u)
        if elapsed >= INTRO_LOAD_SEC + INTRO_SHRINK_SEC:
            self._done = True
            self.win.hud._on_tick_cb = None
            self.win._apply_intro_window_shrink(1.0)
            self.hide()
            self.finished.emit()
            return
        self.update()

    @staticmethod
    def _smoothstep(u: float) -> float:
        u = max(0.0, min(1.0, u))
        return u * u * (3.0 - 2.0 * u)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = float(self.width()), float(self.height())
        s = getattr(self.win, "_scale", 1.0)
        elapsed = max(0.0, time.perf_counter() - self._t0)

        # Target geometry (exact permanent top-left HUD position inside body_container)
        hud_side = max(92.0, float(round(HUD_HEIGHT * s)))
        target_cx = 6.0 + hud_side / 2.0
        target_cy = hud_side / 2.0
        target_scale = hud_side / float(HUD_HEIGHT)
        target_R = max(16.0, hud_side / 2.0 - 10.0 * target_scale)

        # Full-zoom geometry: large and centered inside the big launch dialog box
        zoom_side = min(w * 0.72, h * 0.56)
        zoom_scale = zoom_side / float(HUD_HEIGHT)
        zoom_R = max(64.0, zoom_side / 2.0 - 10.0 * zoom_scale)
        zoom_cx = w / 2.0
        zoom_cy = h * 0.37

        if elapsed <= INTRO_LOAD_SEC:
            load_prog = min(1.0, elapsed / INTRO_LOAD_SEC)
            shrink_u = 0.0
        else:
            load_prog = 1.0
            shrink_u = self._smoothstep((elapsed - INTRO_LOAD_SEC) / INTRO_SHRINK_SEC)

        cur_cx = zoom_cx + (target_cx - zoom_cx) * shrink_u
        cur_cy = zoom_cy + (target_cy - zoom_cy) * shrink_u
        cur_R = zoom_R + (target_R - zoom_R) * shrink_u
        boost = 0.90 * (1.0 - shrink_u)

        # 1. Draw the zoomed/shrinking HUD radar
        self.win.hud.paint_hud_at(p, cur_cx, cur_cy, cur_R, boost_blend=boost)

        # 2. Draw welcome text & animated loading bar (fades out smoothly as box and HUD shrink)
        ui_alpha = max(0.0, 1.0 - shrink_u * 2.4)
        if ui_alpha > 0.01:
            p.save()
            p.setOpacity(ui_alpha)

            ui_scale = max(1.0, min(w / 520.0, h / 680.0))

            # Main welcome title
            title_y = zoom_cy + zoom_R + 36.0 * ui_scale
            title_font = QFont("Segoe UI", max(12, int(round(16.0 * ui_scale))), QFont.Weight.Bold)
            title_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.5 * ui_scale)
            p.setFont(title_font)
            p.setPen(QColor(CYAN_GLOW))
            title_rect = QRectF(16.0, title_y, w - 32.0, 34.0 * ui_scale)
            p.drawText(title_rect, int(Qt.AlignmentFlag.AlignCenter), "WELCOME TO THE INFINITY WORLD")

            # Dynamic stage subtitle
            if load_prog < 0.28:
                stage_txt = "INITIALIZING NEURAL CORE & HOLOGRAPHIC HUD..."
            elif load_prog < 0.58:
                stage_txt = "CALIBRATING VISION, OCR & MOTOR CORTEX..."
            elif load_prog < 0.86:
                stage_txt = "SYNCHRONIZING LOCAL OLLAMA ENGINE..."
            else:
                stage_txt = "ALL AUTONOMOUS SYSTEMS ONLINE · READY"

            sub_y = title_y + 34.0 * ui_scale
            sub_font = QFont("Consolas", max(9, int(round(10.5 * ui_scale))))
            p.setFont(sub_font)
            p.setPen(QColor(ACCENT_VIOLET if load_prog < 0.88 else "#6ee7b7"))
            sub_rect = QRectF(16.0, sub_y, w - 32.0, 24.0 * ui_scale)
            p.drawText(sub_rect, int(Qt.AlignmentFlag.AlignCenter), stage_txt)

            # Loading bar track
            bar_w = min(w * 0.76, 460.0 * ui_scale)
            bar_h = max(9.0, 11.0 * ui_scale)
            bar_x = (w - bar_w) / 2.0
            bar_y = sub_y + 32.0 * ui_scale
            bar_rad = bar_h / 2.0
            track_rect = QRectF(bar_x, bar_y, bar_w, bar_h)

            track_path = QPainterPath()
            track_path.addRoundedRect(track_rect, bar_rad, bar_rad)
            p.fillPath(track_path, QColor(9, 16, 38, 195))
            p.setPen(QPen(QColor(56, 189, 248, 115), 1.1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(track_path)

            # Smooth eased progress fill
            eased_prog = self._smoothstep(load_prog)
            fill_w = max(bar_h, bar_w * eased_prog)
            fill_rect = QRectF(bar_x, bar_y, fill_w, bar_h)
            fill_path = QPainterPath()
            fill_path.addRoundedRect(fill_rect, bar_rad, bar_rad)

            grad = QLinearGradient(fill_rect.topLeft(), fill_rect.topRight())
            grad.setColorAt(0.0, QColor("#06b6d4"))
            grad.setColorAt(0.55, QColor("#6366f1"))
            grad.setColorAt(1.0, QColor("#67e8f9"))
            p.fillPath(fill_path, QBrush(grad))

            # Glowing leading-edge orb on the progress bar
            tip_pt = QPointF(bar_x + fill_w, bar_y + bar_h / 2.0)
            orb_r = bar_h * 1.45
            orb = QRadialGradient(tip_pt, orb_r)
            orb.setColorAt(0.0, QColor(236, 254, 255, 225))
            orb.setColorAt(0.5, QColor(34, 211, 238, 125))
            orb.setColorAt(1.0, QColor(34, 211, 238, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(orb))
            p.drawEllipse(tip_pt, orb_r, orb_r)

            # Percentage readout
            pct_y = bar_y + bar_h + 12.0 * ui_scale
            pct_font = QFont("Consolas", max(10, int(round(11.5 * ui_scale))), QFont.Weight.Bold)
            p.setFont(pct_font)
            p.setPen(QColor(TXT))
            pct_rect = QRectF(bar_x, pct_y, bar_w, 22.0 * ui_scale)
            p.drawText(pct_rect, int(Qt.AlignmentFlag.AlignCenter), f"{int(round(eased_prog * 100))}%")

            p.restore()

        p.end()


# ----------------------------------------------------------------- pill status bubble
class ChromeButton(QPushButton):
    """Titlebar button that paints its own crisp vector icon so glyphs never clip."""

    def __init__(self, kind, parent=None):
        super().__init__("", parent)
        self._kind = kind

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QRectF(self.rect()).center()
        k = min(self.width(), self.height()) * 0.21
        col = QColor("#ffffff") if self.underMouse() else (
            QColor("#fda4af") if self._kind == "close" else QColor("#cbd5e1")
        )
        p.setPen(QPen(col, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if self._kind == "close":
            p.drawLine(QPointF(c.x() - k, c.y() - k), QPointF(c.x() + k, c.y() + k))
            p.drawLine(QPointF(c.x() - k, c.y() + k), QPointF(c.x() + k, c.y() - k))
        elif self._kind == "min":
            p.drawLine(QPointF(c.x() - k, c.y() + k * 0.35), QPointF(c.x() + k, c.y() + k * 0.35))


class StatusBubble(QLabel):
    """True pill-shaped status bubble whose border-radius never exceeds half its inner height."""

    def __init__(self, text="Idle", parent=None):
        super().__init__(text, parent)
        self._fg = "#a5f3fc"
        self._bg = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(8,145,178,165), stop:1 rgba(37,99,235,165))"
        self._bd = "#22d3ee"
        self._pt = 13.5
        self._pad_v = 8
        self._pad_h = 22
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

    def set_theme(self, fg, bg, bd, pt, pad_v, pad_h):
        self._fg, self._bg, self._bd = fg, bg, bd
        self._pt, self._pad_v, self._pad_h = pt, pad_v, pad_h
        self._apply_style()
        self.adjustSize()
        self._apply_style()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_style()

    def _apply_style(self):
        h = self.height() if self.height() > 16 else int(round(self._pt * 1.6 + 2 * self._pad_v))
        rad = max(8, (h - 4) // 2)
        self.setStyleSheet(
            f"background:{self._bg}; color:{self._fg}; border:1px solid {self._bd}; "
            f"border-radius:{rad}px; padding:{self._pad_v}px {self._pad_h}px; "
            f"font-size:{self._pt}pt; font-weight:600;"
        )


# ----------------------------------------------------------------- rounded chat bubbles
class GlassCard(QFrame):
    """Translucent liquid-glass bubble card with frosted smoke, specular sheen, and rim light."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rad = 18.0
        self._tint_a = QColor(14, 58, 92, 130)
        self._tint_b = QColor(13, 94, 116, 115)
        self._rim_col = QColor(56, 189, 248, 150)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_glass(self, rad, tint_a, tint_b, rim_col):
        self._rad = float(rad)
        self._tint_a = QColor(tint_a)
        self._tint_b = QColor(tint_b)
        self._rim_col = QColor(rim_col)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        rad = min(self._rad, max(6.0, (rect.height() - 2.0) / 2.0), max(6.0, (rect.width() - 2.0) / 2.0))
        path = QPainterPath()
        path.addRoundedRect(rect, rad, rad)

        # frosted smoke + translucent gradient body
        p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(path, QColor(8, 12, 34, 68))
        body = QLinearGradient(rect.topLeft(), rect.bottomRight())
        body.setColorAt(0.0, self._tint_a)
        body.setColorAt(1.0, self._tint_b)
        p.fillPath(path, QBrush(body))

        # top specular sheen & bottom caustic glow
        p.save()
        p.setClipPath(path)
        top_h = rect.height() * 0.55
        sh = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + top_h))
        sh.setColorAt(0.0, QColor(255, 255, 255, 44))
        sh.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(rect.left(), rect.top(), rect.width(), top_h), QBrush(sh))

        bot_h = rect.height() * 0.30
        bg = QLinearGradient(QPointF(rect.left(), rect.bottom()), QPointF(rect.left(), rect.bottom() - bot_h))
        bg.setColorAt(0.0, QColor(255, 255, 255, 22))
        bg.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(rect.left(), rect.bottom() - bot_h, rect.width(), bot_h), QBrush(bg))
        p.restore()

        # glass rim highlight
        rim = QLinearGradient(rect.topLeft(), rect.bottomRight())
        rim.setColorAt(0.0, QColor(255, 255, 255, 165))
        rim.setColorAt(0.45, self._rim_col)
        rim.setColorAt(1.0, QColor(255, 255, 255, 85))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QBrush(rim), 1.2))
        p.drawRoundedRect(rect, rad, rad)


class BubbleRow(QWidget):
    """A single chat row containing a genuinely rounded QFrame bubble."""

    def __init__(self, kind, payload, scale=1.0, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.payload = payload
        self._scale = scale
        self._expanded = False
        self._wf_total = 0.0

        outer = QHBoxLayout(self)
        outer.setContentsMargins(2, 3, 2, 3)
        outer.setSpacing(0)

        self.card = GlassCard()
        self.card.setObjectName("bubbleCard")
        inner = QVBoxLayout(self.card)
        inner.setSpacing(4)

        self.header = QLabel()
        self.header.setTextFormat(Qt.TextFormat.RichText)
        self.toggle_btn = None
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setOpenExternalLinks(True)
        self.body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )

        if kind == "user":
            self.card.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            outer.addStretch(1)
            outer.addWidget(self.card)
            self.header.setText("YOU")
            self.header.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self.body.setAlignment(Qt.AlignmentFlag.AlignLeft)
            inner.addWidget(self.header)
            inner.addWidget(self.body)
        elif kind == "workflow":
            self.card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            outer.addWidget(self.card)
            self.header.hide()
            self.toggle_btn = QPushButton("⚙  Time taken: 0.0s  ▸")
            self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.toggle_btn.clicked.connect(self._toggle_expand)
            self.body.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self.body.setVisible(False)
            inner.addWidget(self.toggle_btn)
            inner.addWidget(self.body)
        elif kind == "bot":
            self.card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            outer.addWidget(self.card)
            self.header.setText("INFINITY")
            self.header.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self.body.setAlignment(Qt.AlignmentFlag.AlignLeft)
            inner.addWidget(self.header)
            inner.addWidget(self.body)
        elif kind == "log":
            self.card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            outer.addWidget(self.card)
            self.header.setText("CONSOLE")
            self.header.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self.body.setAlignment(Qt.AlignmentFlag.AlignLeft)
            inner.addWidget(self.header)
            inner.addWidget(self.body)
        elif kind in ("pill", "welcome"):
            self.card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            outer.addWidget(self.card)
            self.header.hide()
            self.body.setAlignment(Qt.AlignmentFlag.AlignCenter)
            inner.addWidget(self.body)

        self._inner_layout = inner
        self.apply_scale(scale)
        self.update_content(payload)

    def _toggle_expand(self):
        self._expanded = not self._expanded
        self.body.setVisible(self._expanded)
        self._refresh_wf_header()

    def set_workflow_total(self, total_sec):
        self._wf_total = total_sec
        self._refresh_wf_header()

    def _refresh_wf_header(self):
        if self.toggle_btn is None:
            return
        arrow = "▾" if self._expanded else "▸"
        self.toggle_btn.setText(f"⚙  Time taken: {self._wf_total:.1f}s  {arrow}")

    def apply_scale(self, s):
        self._scale = s
        rad = max(14, int(round(18 * s)))
        pad_v = max(6, int(round(10 * s)))
        pad_h = max(10, int(round(14 * s)))
        lbl_pt = round(10.5 * s, 1)
        body_pt = round(12.5 * s, 1)

        if self.kind in ("pill", "welcome"):
            pad_v = max(4, int(round(6 * s)))
            pad_h = max(10, int(round(14 * s)))
            rad = max(12, int(round(16 * s)))
        elif self.kind == "log":
            pad_v = max(6, int(round(8 * s)))
            pad_h = max(10, int(round(12 * s)))
            rad = max(12, int(round(16 * s)))

        self._inner_layout.setContentsMargins(pad_h, pad_v, pad_h, pad_v)

        if self.kind == "user":
            ta, tb = QColor(80, 125, 255, 160), QColor(145, 90, 255, 145)
            rim_c, hdr_col = QColor(56, 189, 248, 165), CYAN_GLOW
        elif self.kind == "workflow":
            ta, tb = QColor(76, 29, 149, 135), QColor(30, 27, 75, 125)
            rim_c, hdr_col = QColor(167, 139, 250, 155), ACCENT_VIOLET
        elif self.kind == "bot":
            ta, tb = QColor(255, 255, 255, 38), QColor(34, 211, 238, 42)
            rim_c, hdr_col = QColor(34, 211, 238, 150), CYAN
        elif self.kind == "pill":
            _text, pkind = self.payload
            ta, tb, rim_c, hdr_col = {
                "info": (QColor(30, 64, 135, 135), QColor(14, 90, 128, 125), QColor(56, 189, 248, 140), CYAN_GLOW),
                "dim": (QColor(40, 52, 95, 125), QColor(24, 32, 64, 115), QColor(148, 163, 184, 115), TXT),
                "ok": (QColor(13, 94, 76, 135), QColor(16, 115, 86, 125), QColor(52, 211, 153, 145), "#6ee7b7"),
                "err": (QColor(136, 19, 55, 145), QColor(102, 22, 48, 135), QColor(251, 113, 133, 155), "#fda4af"),
            }[pkind]
        elif self.kind == "welcome":
            ta, tb = QColor(13, 94, 82, 120), QColor(14, 95, 115, 105)
            rim_c, hdr_col = QColor(52, 211, 153, 140), "#6ee7b7"
        else:
            ta, tb = QColor(12, 24, 54, 160), QColor(15, 23, 42, 145)
            rim_c, hdr_col = QColor(56, 189, 248, 135), CYAN_GLOW

        self.card.setStyleSheet("QFrame#bubbleCard { background: transparent; border: none; }")
        self.card.set_glass(rad, ta, tb, rim_c)
        self.header.setStyleSheet(
            f"color:{hdr_col}; font-size:{lbl_pt}pt; font-weight:700; background:transparent; border:none;"
        )
        if self.toggle_btn is not None:
            self.toggle_btn.setStyleSheet(
                f"QPushButton {{ color:{ACCENT_VIOLET}; font-size:{round(11.0 * s, 1)}pt; font-weight:700; "
                f"background:transparent; border:none; text-align:center; padding:2px 0; }}"
                f"QPushButton:hover {{ color:#ddd6fe; }}"
            )
        self.body.setStyleSheet(
            f"color:{TXT}; font-size:{body_pt}pt; background:transparent; border:none;"
        )
        self.update_content(self.payload)

    def set_max_width(self, viewport_w):
        if self.kind == "user":
            self.card.setMaximumWidth(max(160, int(viewport_w * 0.78)))
        else:
            self.card.setMaximumWidth(max(220, int(viewport_w - 8)))

    def update_content(self, payload):
        self.payload = payload
        s = self._scale
        if self.kind == "user":
            self.body.setText(html.escape(payload, quote=False).replace("\n", "<br>"))
        elif self.kind == "workflow":
            rows = []
            for status, label in payload:
                dot_col = {"ok": "#34d399", "err": "#fb7185", "pending": "#fbbf24", "time": CYAN_GLOW}.get(status, MUTED)
                rows.append(
                    f'<p style="margin:2px 0; font-size:{round(11.0 * s, 1)}pt;">'
                    f'<span style="color:{dot_col}; font-size:{round(12.5 * s, 1)}pt;">●</span> '
                    f'<span style="color:{TXT};">{html.escape(label)}</span></p>'
                )
            self.body.setText("".join(rows))
            self._refresh_wf_header()
        elif self.kind == "bot":
            self.body.setText(md_to_html(payload, scale=s))
        elif self.kind == "pill":
            text, pkind = payload
            col = {"info": CYAN_GLOW, "dim": TXT, "ok": "#6ee7b7", "err": "#fda4af"}[pkind]
            self.body.setText(f'<span style="color:{col}; font-size:{round(10.5 * s, 1)}pt;">{html.escape(text)}</span>')
        elif self.kind == "welcome":
            self.body.setText(
                f'<span style="color:#6ee7b7; font-size:{round(11.0 * s, 1)}pt; font-weight:600;">● Infinity online</span><br>'
                f'<span style="color:{MUTED}; font-size:{round(10.5 * s, 1)}pt;">'
                f'Enter to send · Shift+Enter for newline · <code>/tools</code> <code>/reset</code> <code>/do</code></span>'
            )
        elif self.kind == "log":
            lines = payload if isinstance(payload, list) else [str(payload)]
            formatted_lines = []
            for ln in lines:
                esc = html.escape(str(ln), quote=False)
                esc = re.sub(r"([\\/])", r"\1&#8203;", esc)
                if ln.startswith("Running "):
                    formatted_lines.append(
                        f'<div style="color:{CYAN_GLOW}; font-weight:600; margin-bottom:4px;">{esc}</div>'
                    )
                else:
                    formatted_lines.append(f'<div style="color:{_CODE_FG}; margin:1px 0;">{esc}</div>')
            pt = round(11.0 * s, 1)
            self.body.setText(
                f'<div style="font-family:Consolas,monospace; font-size:{pt}pt; text-align:left;">'
                + "".join(formatted_lines)
                + "</div>"
            )


class ChatArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._at_bottom = True
        self._scale = 1.0
        self.rows = []

        self._container = QWidget()
        self._container.setStyleSheet("background:transparent;")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(6)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setWidget(self._container)

        sb = self.verticalScrollBar()
        sb.valueChanged.connect(self._on_scroll)
        sb.rangeChanged.connect(self._on_range)

    def _on_scroll(self, val):
        sb = self.verticalScrollBar()
        self._at_bottom = val >= sb.maximum() - 12

    def _on_range(self, _min, max_val):
        if self._at_bottom:
            self.verticalScrollBar().setValue(max_val)

    def add_bubble(self, kind, payload):
        row = BubbleRow(kind, payload, scale=self._scale)
        row.set_max_width(self.viewport().width())
        self.rows.append(row)
        self._layout.addWidget(row)
        return row

    def apply_scale(self, s):
        self._scale = s
        vw = self.viewport().width()
        for row in self.rows:
            row.apply_scale(s)
            row.set_max_width(vw)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        vw = self.viewport().width()
        for row in self.rows:
            row.set_max_width(vw)

    def clear_all(self):
        for row in self.rows:
            self._layout.removeWidget(row)
            row.deleteLater()
        self.rows.clear()


# ----------------------------------------------------------------- small widgets
class PromptEdit(QPlainTextEdit):
    submitted = pyqtSignal()
    heightChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("Ask Infinity...")
        self.setTabChangesFocus(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(0)
        self._scale = 1.0
        self._font_pt = 12.5
        self._single_h = 46
        self.document().contentsChanged.connect(self._fit)
        self.apply_scale(1.0)

    def apply_scale(self, s):
        self._scale = s
        self._font_pt = round(12.5 * s, 1)
        font = QFont("Segoe UI")
        font.setPointSizeF(self._font_pt)
        self.setFont(font)
        self.document().setDefaultFont(font)
        self.document().setDocumentMargin(0)
        self._fit()

    def _fit(self):
        s = getattr(self, "_scale", 1.0)
        font = QFont("Segoe UI")
        font.setPointSizeF(getattr(self, "_font_pt", round(12.5 * s, 1)))
        fm = QFontMetrics(font)
        line_h = fm.lineSpacing()
        block_cnt = max(1, self.document().blockCount())
        doc_lines = int(round(self.document().size().height()))
        lines = max(1, min(5, max(block_cnt, doc_lines)))

        single_h = max(44, int(round(46 * s)))
        if (single_h - line_h) % 2 != 0:
            single_h += 1
        self._single_h = single_h
        pad_v = max(6, (single_h - 4 - line_h) // 2)
        pad_h = max(12, int(round(16 * s)))
        h = single_h if lines == 1 else (line_h * lines + 2 * pad_v + 4)

        rad = max(12, (single_h - 4) // 2)
        self.setStyleSheet(
            f"QPlainTextEdit {{ background:rgba(8,14,34,115); border:1.5px solid rgba(34,211,238,165); "
            f"border-radius:{rad}px; padding:{pad_v}px {pad_h}px; color:{TXT}; "
            f"font-family:'Segoe UI','Inter',sans-serif; font-size:{self._font_pt}pt; "
            f"selection-background-color:{RING_B}; }}"
            f"QPlainTextEdit:focus {{ border:1.5px solid {CYAN_GLOW}; }}"
        )
        self.setFixedHeight(h)
        self.heightChanged.emit(h)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(e)


class TopBar(QWidget):
    def __init__(self, win):
        super().__init__(win)
        self.win = win

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            h = self.win.windowHandle()
            if h is not None and h.startSystemMove():
                return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        pass


class Bridge(QObject):
    event = pyqtSignal(int, str, str)      # job id, kind, text
    done = pyqtSignal(int, str, bool)      # job id, answer, ok
    ask = pyqtSignal(str, str, object)     # kind, text, holder


class _Holder:
    def __init__(self):
        self.ev = threading.Event()
        self.value = None


class _EmitWriter:
    """File-like object that forwards complete lines to a callback."""
    def __init__(self, emit):
        self._emit, self._buf = emit, ""

    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._emit(line)
        return len(s)

    def flush(self):
        if self._buf.strip():
            self._emit(self._buf)
        self._buf = ""

    def isatty(self):
        return False


# ----------------------------------------------------------------- main window
class GlassWindow(QWidget):
    def __init__(self, agent, commands=None):
        super().__init__()
        self.agent, self.commands = agent, commands
        self.bridge = Bridge()
        self.bridge.event.connect(self._on_event)
        self.bridge.done.connect(self._on_done)
        self.bridge.ask.connect(self._on_ask)

        self._jobs = queue.Queue()
        self._busy_lock = threading.Lock()
        self._worker_busy = False
        self._worker_tid = None
        self._next_id = 0
        self._active = None          # job id currently shown as running
        self._cur_id = 0             # job id the worker is executing
        self._busy = False
        self._blur, self._rounded = False, False
        self._opacity = IDLE_OPACITY
        self._scale = 1.0
        self._launch_size = (880, 960)
        self._final_size = (int(BASE_W), int(BASE_H))
        self._screen_rect = None
        self._active_wf_row = None   # BubbleRow for current workflow
        self._active_bot_row = None  # BubbleRow for streaming bot response
        self._active_log_row = None  # BubbleRow for grouped console/command output
        self._stream_tokens = []
        self._stream_buf = ""

        # Successive per-phase timing
        self._phase = "idle"         # "idle" | "thinking" | "working" | "generating"
        self._phase_t0 = 0.0
        self._phase_totals = {"thinking": 0.0, "working": 0.0, "generating": 0.0}
        self._phase_recorded = set()
        self._status_text = "Idle"
        self._status_hud_state = "idle"

        self.setWindowTitle("Infinity")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(360, 520)
        self.setMouseTracking(True)
        self.resize(int(BASE_W), int(BASE_H))
        self._build_ui()
        self._apply_scale(1.0)
        self._apply_opacity(self._opacity)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(320)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim.valueChanged.connect(self._anim_step)

        self._wf_timer = QTimer(self)
        self._wf_timer.setInterval(100)
        self._wf_timer.timeout.connect(self._tick_workflow_timer)

        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(20)
        self._stream_timer.timeout.connect(self._stream_tick)

        self._clock = QTimer(self)
        self._clock.setTimerType(Qt.TimerType.PreciseTimer)
        self._clock.timeout.connect(self._tick_clock)
        self._tick_clock()
        QTimer.singleShot(60000 - int(time.time() * 1000) % 60000, self._start_clock)

        self._thread = threading.Thread(target=self._worker, name="infinity-agent", daemon=True)
        self._thread.start()
        self.agent.on_event = self._agent_event
        self.chat.add_bubble("welcome", None)

    # ---- UI construction
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10 + EDGE + 4, 10 + EDGE + 2, 10 + EDGE + 4, 10 + EDGE + 4)
        root.setSpacing(6)

        # top bar: title on left, bigger time (HH:MM AM/PM) + min/close on right
        self.bar = TopBar(self)
        bl = QHBoxLayout(self.bar)
        bl.setContentsMargins(6, 0, 2, 0)
        bl.setSpacing(8)
        self.title_lbl = QLabel("◈ INFINITY")
        self.clock = QLabel()
        self.clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mn = ChromeButton("min", self.bar)
        self.mn.setObjectName("tb")
        self.mn.clicked.connect(self.showMinimized)
        self.cl = ChromeButton("close", self.bar)
        self.cl.setObjectName("close")
        self.cl.clicked.connect(self.close)
        for b in (self.mn, self.cl):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        bl.addWidget(self.title_lbl)
        bl.addStretch(1)
        bl.addWidget(self.mn)
        bl.addWidget(self.cl)
        root.addWidget(self.bar)

        # Main workspace container (hidden during the startup intro)
        self.body_container = QWidget(self)
        body_layout = QVBoxLayout(self.body_container)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(6)

        # HUD animation on left + stacked clock & status pill beside it
        self.hud_row = QHBoxLayout()
        hud_row = self.hud_row
        hud_row.setContentsMargins(6, 0, 6, 0)
        hud_row.setSpacing(32)
        self.hud = HudWidget()
        self.status_bubble = StatusBubble("Idle")
        status_col = QVBoxLayout()
        status_col.setContentsMargins(0, 0, 0, 0)
        status_col.setSpacing(8)
        status_col.addStretch(1)
        status_col.addWidget(self.clock, 0, Qt.AlignmentFlag.AlignCenter)
        status_col.addWidget(self.status_bubble, 0, Qt.AlignmentFlag.AlignCenter)
        status_col.addStretch(1)
        hud_row.addWidget(self.hud, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hud_row.addLayout(status_col)
        hud_row.addStretch(1)
        body_layout.addLayout(hud_row)

        self.chat = ChatArea()
        self.chat.setObjectName("chatArea")
        body_layout.addWidget(self.chat, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.input = PromptEdit()
        self.input.submitted.connect(self._submit)
        self.send = QPushButton("➤")
        self.send.setObjectName("send")
        self.send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send.clicked.connect(self._send_clicked)
        self.input.heightChanged.connect(self._sync_send_height)
        row.addWidget(self.input, 1)
        row.addWidget(self.send, 0, Qt.AlignmentFlag.AlignBottom)
        body_layout.addLayout(row)

        # Full-zoom startup intro overlay (shown first when launched)
        self.intro_overlay = IntroOverlay(self)
        self.intro_overlay.finished.connect(self._on_intro_finished)

        root.addWidget(self.intro_overlay, 1)
        root.addWidget(self.body_container, 1)
        self.body_container.hide()

        if not sys.platform.startswith("win"):
            grip = QSizeGrip(self)
            grip.setFixedSize(14, 14)
            self._grip = grip
        self._apply_status_bubble("Idle", "idle")

    def _apply_intro_window_shrink(self, shrink_u: float):
        """Smoothly shrink the dialog box from launch size to post-launch size while keeping it centered on screen."""
        scr = self._screen_rect or QApplication.primaryScreen().availableGeometry()
        lw, lh = self._launch_size
        fw, fh = self._final_size
        cur_w = int(round(lw + (fw - lw) * shrink_u))
        cur_h = int(round(lh + (fh - lh) * shrink_u))
        cx = scr.left() + (scr.width() - cur_w) // 2
        cy = scr.top() + (scr.height() - cur_h) // 2
        self.setGeometry(cx, cy, cur_w, cur_h)

    def _on_intro_finished(self):
        self.intro_overlay.hide()
        self.body_container.show()
        self._apply_scale(self._compute_scale())
        self.input.setFocus()

    def _sync_send_height(self, h):
        if not hasattr(self, "send"):
            return
        s = getattr(self, "_scale", 1.0)
        single_h = getattr(self.input, "_single_h", max(44, int(round(46 * s))))
        btn_h = single_h if h <= single_h + 2 else h
        btn_w = max(single_h, int(round(52 * s)))
        rad = max(12, (min(btn_w, btn_h) - 4) // 2)
        base_pt = round(13.0 * s, 1)
        stop = bool(self.send.property("stop"))
        if stop:
            bg = "#f43f5e"
            hover_bg = "#fb7185"
        else:
            bg = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #06b6d4, stop:1 #6366f1)"
            hover_bg = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #22d3ee, stop:1 #818cf8)"
        self.send.setFixedSize(btn_w, btn_h)
        self.send.setStyleSheet(
            f"QPushButton#send {{ background:{bg}; color:white; border:none; "
            f"border-radius:{rad}px; font-weight:600; font-size:{base_pt}pt; }}"
            f"QPushButton#send:hover {{ background:{hover_bg}; }}"
        )

    def _apply_status_bubble(self, text, hud_state):
        self._status_text = text
        self._status_hud_state = hud_state
        s = self._scale
        pt = round(13.0 * s, 1)
        pad_v = max(6, int(round(8 * s)))
        pad_h = max(16, int(round(22 * s)))
        if hud_state == "working":
            fg, bg, bd = "#fecdd3", "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(225,29,72,175), stop:1 rgba(147,51,234,170))", "#fb7185"
        elif hud_state == "generating":
            fg, bg, bd = "#fef3c7", "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(217,119,6,175), stop:1 rgba(225,29,72,165))", "#fbbf24"
        else:
            fg, bg, bd = "#a5f3fc", "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(8,145,178,165), stop:1 rgba(37,99,235,165))", "#22d3ee"
        self.status_bubble.setText(text)
        self.status_bubble.set_theme(fg, bg, bd, pt, pad_v, pad_h)

    # ---- per-state timer helpers
    def _reset_timers(self):
        self._phase = "idle"
        self._phase_t0 = 0.0
        self._phase_totals = {"thinking": 0.0, "working": 0.0, "generating": 0.0}
        self._phase_recorded = set()

    def _switch_phase(self, new_phase):
        now = time.perf_counter()
        prev = self._phase
        if prev in self._phase_totals and self._phase_t0 > 0:
            self._phase_totals[prev] += max(0.0, now - self._phase_t0)
            if prev != new_phase and prev not in self._phase_recorded:
                t_prev = self._phase_totals[prev]
                if t_prev >= 0.05:
                    self._record_phase_line(prev, t_prev)
                self._phase_recorded.add(prev)
        self._phase = new_phase
        self._phase_t0 = now if new_phase != "idle" else 0.0
        if new_phase == "idle":
            self._wf_timer.stop()
        elif not self._wf_timer.isActive():
            self._wf_timer.start()
        self._tick_workflow_timer()

    def _record_phase_line(self, phase, seconds):
        if phase == "thinking":
            self._add_workflow_step("time", f"Thought for {seconds:.1f}s")
        elif phase == "working":
            self._add_workflow_step("time", f"Worked for {seconds:.1f}s")
        elif phase == "generating":
            self._add_workflow_step("time", f"Generated in {seconds:.1f}s")

    def _total_elapsed(self):
        total = sum(self._phase_totals.values())
        if self._phase in self._phase_totals and self._phase_t0 > 0:
            total += max(0.0, time.perf_counter() - self._phase_t0)
        return total

    def _tick_workflow_timer(self):
        if self._active_wf_row is not None:
            self._active_wf_row.set_workflow_total(self._total_elapsed())

    def _compute_scale(self):
        s = min(self.width() / BASE_W, self.height() / BASE_H)
        return max(0.75, min(1.22, s))

    def _apply_scale(self, s):
        self._scale = s
        base_pt = round(12.5 * s, 1)
        tb_pt = round(11.0 * s, 1)
        title_pt = round(12.0 * s, 1)
        btn_w, btn_h = max(24, int(round(30 * s))), max(22, int(round(26 * s)))
        btn_rad = max(8, (btn_h - 4) // 2)

        self.setStyleSheet(f"""
            QWidget {{ color:{TXT}; font-family:'Segoe UI','Inter',sans-serif; font-size:{base_pt}pt; }}
            QLabel {{ background:transparent; }}
            QPushButton#tb {{ background:rgba(51,92,156,95); border:1px solid rgba(56,189,248,110);
                              border-radius:{btn_rad}px; padding:2px 6px;
                              color:#cbd5e1; font-size:{tb_pt}pt; }}
            QPushButton#tb:hover {{ background:rgba(34,211,238,110); color:white; }}
            QPushButton#close {{ background:rgba(51,92,156,95); border:1px solid rgba(244,63,94,120);
                                 border-radius:{btn_rad}px; color:#fda4af; font-size:{tb_pt}pt; }}
            QPushButton#close:hover {{ background:rgba(244,63,94,190); color:white; }}
            QScrollArea#chatArea {{ background:transparent; border:none; }}
            QScrollBar:vertical {{ background:rgba(10,16,38,60); width:10px; margin:2px 2px; border-radius:5px; }}
            QScrollBar::handle:vertical {{ background:rgba(34,211,238,140); border-radius:3px; min-height:24px; }}
            QScrollBar::handle:vertical:hover {{ background:rgba(103,232,249,210); }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:transparent; }}
        """)

        self.title_lbl.setStyleSheet(f"color:{CYAN}; font-weight:700; letter-spacing:2px; font-size:{title_pt}pt;")
        self.mn.setFixedSize(btn_w, btn_h)
        self.cl.setFixedSize(btn_w, btn_h)
        self.bar.setFixedHeight(max(30, int(round(40 * s))))

        self.hud_row.setSpacing(max(20, int(round(32 * s))))
        hud_side = max(92, int(round(HUD_HEIGHT * s)))
        self.hud.setFixedSize(hud_side, hud_side)
        self.hud.update()

        self._tick_clock()
        self._apply_status_bubble(getattr(self, "_status_text", "Idle"), getattr(self, "_status_hud_state", "idle"))

        self.chat.apply_scale(s)
        self.input.apply_scale(s)
        self._sync_send_height(self.input.height())

    # ---- window chrome
    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_shown_once", False):
            self._shown_once = True
            self._blur, self._rounded = False, True
            scr = QApplication.primaryScreen().availableGeometry()
            self._screen_rect = scr

            # Launch size: ~46.2% screen width x ~93.6% screen height, centered on screen
            lw = max(560, int(round(scr.width() * LAUNCH_W_RATIO)))
            lh = max(680, int(round(scr.height() * LAUNCH_H_RATIO)))
            self._launch_size = (lw, lh)

            # Post-launch size: ~27.8% screen width x ~68.0% screen height, centered on screen
            fw = max(480, int(round(scr.width() * FINAL_W_RATIO)))
            fh = max(640, int(round(scr.height() * FINAL_H_RATIO)))
            self._final_size = (fw, fh)

            self._apply_intro_window_shrink(0.0)
            self.intro_overlay.start()
            self.update()
        self.hud.pause(False)

    def hideEvent(self, e):
        self.hud.pause(True)
        super().hideEvent(e)

    def changeEvent(self, e):
        super().changeEvent(e)
        hud = getattr(self, "hud", None)
        if hud is not None:
            hud.pause(self.isMinimized())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        s = self._compute_scale()
        if abs(s - self._scale) > 0.01:
            self._apply_scale(s)
        else:
            self.input._fit()
            self._sync_send_height(self.input.height())
        g = getattr(self, "_grip", None)
        if g:
            g.move(self.width() - g.width() - 2, self.height() - g.height() - 2)

    def _edges_at(self, pos):
        m = 10 + EDGE
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        edges = None
        for cond, flag in ((x < m, Qt.Edge.LeftEdge), (x >= w - m, Qt.Edge.RightEdge),
                           (y < m, Qt.Edge.TopEdge), (y >= h - m, Qt.Edge.BottomEdge)):
            if cond:
                edges = flag if edges is None else edges | flag
        return edges

    def mouseMoveEvent(self, e):
        ed = self._edges_at(e.position().toPoint())
        L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        if ed is None:
            self.unsetCursor()
        elif ed in (L, R):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif ed in (T, B):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif ed in (L | T, R | B):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            ed = self._edges_at(e.position().toPoint())
            if ed is not None and self.windowHandle() is not None:
                self.windowHandle().startSystemResize(ed)
                return
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        M = 10
        rad = 28.0 * self._scale
        body = QRectF(self.rect()).adjusted(M, M, -M, -M)
        p.setPen(Qt.PenStyle.NoPen)
        for k in range(M):
            p.setBrush(QColor(0, 0, 0, 7))
            p.drawRoundedRect(body.adjusted(-k, -k + 2, k, k + 2), rad + k, rad + k)
        path = QPainterPath()
        path.addRoundedRect(body, rad, rad)
        v = self._opacity
        bg_grad = QLinearGradient(body.topLeft(), body.bottomRight())
        bg_grad.setColorAt(0.0, QColor(11, 16, 48, int(180 + 65 * v)))
        bg_grad.setColorAt(1.0, QColor(28, 16, 70, int(180 + 65 * v)))
        p.fillPath(path, QBrush(bg_grad))
        p.save()
        p.setClipPath(path)
        blob_r = max(body.width(), body.height()) * 0.55
        for bx, by, col_hex, ba in (
            (0.20, 0.45, "#3D6BFF", 0.24),
            (0.82, 0.55, "#9B4DFF", 0.26),
            (0.35, 0.85, "#00D4B4", 0.20),
        ):
            rg = QRadialGradient(QPointF(body.left() + body.width() * bx, body.top() + body.height() * by), blob_r)
            c0, c1 = QColor(col_hex), QColor(col_hex)
            c0.setAlphaF(ba * v)
            c1.setAlphaF(0.0)
            rg.setColorAt(0.0, c0)
            rg.setColorAt(1.0, c1)
            p.fillRect(body, QBrush(rg))
        p.restore()
        sheen = QLinearGradient(body.topLeft(), QPointF(body.right(), body.top() + 240 * self._scale))
        sheen.setColorAt(0.0, QColor(34, 211, 238, int(48 * v)))
        sheen.setColorAt(0.55, QColor(124, 58, 237, int(36 * v)))
        sheen.setColorAt(1.0, QColor(16, 25, 53, 0))
        p.setClipPath(path)
        p.fillRect(QRectF(body.left(), body.top(), body.width(), 240 * self._scale), QBrush(sheen))
        p.setClipping(False)
        border_grad = QLinearGradient(body.topLeft(), body.bottomRight())
        alpha_b = int(230 * min(1.0, v + 0.15))
        border_grad.setColorAt(0.0, QColor(34, 211, 238, alpha_b))
        border_grad.setColorAt(1.0, QColor(167, 139, 250, alpha_b))
        p.setPen(QPen(QBrush(border_grad), 1.6))
        p.drawPath(path)

    def closeEvent(self, e):
        self._clock.stop()
        self._wf_timer.stop()
        self._stream_timer.stop()
        self.hud.pause(True)
        self._cancel_running()
        QApplication.quit()
        e.accept()

    # ---- opacity logic
    def _apply_opacity(self, v):
        self._opacity = v
        self.hud.alpha = 0.35 + 0.65 * v
        self.update()

    def _anim_step(self, v):
        self._apply_opacity(float(v))

    def _fade_to(self, target):
        target = max(MIN_OPACITY, min(1.0, target))
        self._anim.stop()
        self._anim.setStartValue(self._opacity)
        self._anim.setEndValue(target)
        self._anim.start()

    # ---- clock
    def _start_clock(self):
        self._tick_clock()
        self._clock.start(60000)

    def _tick_clock(self):
        t = time.localtime()
        time_pt = round(CLOCK_PT * self._scale, 1)
        ampm_pt = round(time_pt * 0.45, 1)
        self.clock.setText(
            f'<span style="color:{CYAN_GLOW}; font-family:Consolas,monospace; font-size:{time_pt}pt; font-weight:700;">{time.strftime("%I:%M", t)}</span> '
            f'<span style="color:{ACCENT_VIOLET}; font-size:{ampm_pt}pt; font-weight:600;">{time.strftime("%p", t)}</span>'
        )

    # ---- workflow & streaming helpers
    def _ensure_workflow_row(self):
        if self._active_wf_row is None:
            self._active_wf_row = self.chat.add_bubble("workflow", [])
        return self._active_wf_row

    def _add_workflow_step(self, status, label):
        row = self._ensure_workflow_row()
        row.payload.append([status, label])
        row.update_content(row.payload)

    def _resolve_workflow_step(self, status):
        if self._active_wf_row is None:
            return
        for step in reversed(self._active_wf_row.payload):
            if step[0] == "pending":
                step[0] = status
                self._active_wf_row.update_content(self._active_wf_row.payload)
                return

    def _finalize_workflow(self, ok=True):
        if self._active_wf_row is None:
            return
        changed = False
        for step in self._active_wf_row.payload:
            if step[0] == "pending":
                step[0] = "ok" if ok else "err"
                changed = True
        if changed:
            self._active_wf_row.update_content(self._active_wf_row.payload)
        self._active_wf_row.set_workflow_total(self._total_elapsed())

    def _append_stream_chunk(self, chunk):
        self._stream_buf += chunk
        if self._active_bot_row is None:
            self._active_bot_row = self.chat.add_bubble("bot", self._stream_buf)
        else:
            self._active_bot_row.update_content(self._stream_buf)

    def _start_token_stream(self, text):
        self._stream_timer.stop()
        self._stream_buf = ""
        tokens = re.findall(r"\S+\s*|\n", text) or [text]
        batch = max(1, len(tokens) // 70)
        self._stream_tokens = ["".join(tokens[i:i + batch]) for i in range(0, len(tokens), batch)]
        self._stream_timer.start()

    def _stream_tick(self):
        if not self._stream_tokens:
            self._stream_timer.stop()
            self._switch_phase("idle")
            self._finalize_workflow(ok=True)
            self._active_wf_row = None
            self._active_bot_row = None
            self._active_log_row = None
            self._set_busy(False, hud_state="idle", status_text="Idle")
            self.input.setFocus()
            return
        chunk = self._stream_tokens.pop(0)
        self._append_stream_chunk(chunk)

    # ---- state transitions
    def _set_busy(self, busy, hud_state=None, status_text=None):
        self._busy = busy
        target_state = hud_state if hud_state else ("working" if busy else "idle")
        self.hud.set_state(target_state)
        if status_text is not None:
            self._apply_status_bubble(status_text, target_state)
        self.send.setText("■" if busy else "➤")
        self.send.setProperty("stop", busy)
        self._sync_send_height(self.input.height())
        self._fade_to(WORK_OPACITY if busy else IDLE_OPACITY)
        set_click_through(int(self.winId()), busy)

    def _submit(self):
        text = self.input.toPlainText().strip()
        if not text or self._busy:
            return
        self._stream_timer.stop()
        self._stream_tokens.clear()
        self._stream_buf = ""
        self._active_wf_row = None
        self._active_bot_row = None
        self._active_log_row = None
        self.input.clear()
        self.chat.add_bubble("user", text)
        self._next_id += 1
        self._active = self._next_id
        self._reset_timers()
        self._ensure_workflow_row()
        self._set_busy(True, hud_state="working", status_text="Thinking")
        self._switch_phase("thinking")
        self._jobs.put((self._next_id, text))

    def _send_clicked(self):
        if self._busy:
            self._stop()
        else:
            self._submit()

    def _stop(self):
        self._active = None
        self._stream_timer.stop()
        self._stream_tokens.clear()
        self._switch_phase("idle")
        self._finalize_workflow(ok=False)
        self._active_wf_row = None
        self._active_bot_row = None
        self._active_log_row = None
        self._cancel_running()
        self.chat.add_bubble("pill", ("■ Stopped", "dim"))
        self._set_busy(False, hud_state="idle", status_text="Idle")

    def _cancel_running(self):
        try:
            from core import safety
            safety.KILL.set()
        except Exception:
            pass
        try:
            import tools
            tools.STATE["abort"] = True
        except Exception:
            pass
        with self._busy_lock:
            if self._worker_busy and self._worker_tid:
                ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(self._worker_tid),
                                                           ctypes.py_object(AgentStopped))

    # ---- signals from worker (UI thread)
    def _on_event(self, jid, kind, text):
        if jid != self._active and kind != "log":
            return
        if kind == "log":
            stripped = text.strip()
            if not stripped or re.match(r"^[-=]{5,}$", stripped):
                return
            if self._active_log_row is None:
                self._active_log_row = self.chat.add_bubble("log", [stripped])
            else:
                self._active_log_row.payload.append(stripped)
                self._active_log_row.update_content(self._active_log_row.payload)
            return

        if kind in ("token", "stream", "chunk", "delta"):
            self.hud.set_state("generating")
            self._apply_status_bubble("Processing", "generating")
            if self._phase != "generating":
                self._switch_phase("generating")
            self._append_stream_chunk(text)
            return

        if kind in ("generating", "output", "response_start", "answer", "final"):
            self.hud.set_state("generating")
            self._apply_status_bubble("Processing", "generating")
            if self._phase != "generating":
                self._switch_phase("generating")
            return

        if kind == "skill_start":
            self.hud.set_state("working")
            self._apply_status_bubble("Processing", "working")
            if self._phase != "working":
                self._switch_phase("working")
            short = text if len(text) < 70 else text[:67] + "…"
            self._add_workflow_step("pending", short)
        elif kind == "skill_end":
            self._resolve_workflow_step("ok")
        elif kind == "tool_call":
            self.hud.set_state("working")
            self._apply_status_bubble("Tool calling", "working")
            if self._phase != "working":
                self._switch_phase("working")
            m = re.search(r"(?:\]\s*|⚙\s*)(\w+)\(", text)
            tool_name = m.group(1) if m else "tool"
            self._add_workflow_step("pending", f"Tool: {tool_name}")
        elif kind == "tool_result":
            failed = bool(re.search(r"(?:->|→)\s*(Error|Failed|Exception)", text, re.IGNORECASE))
            self._resolve_workflow_step("err" if failed else "ok")
            self._apply_status_bubble("Processing", "working")

    def _on_done(self, jid, answer, ok):
        if jid != self._active:
            return
        self._active = None

        if not ok:
            self._switch_phase("idle")
            self._finalize_workflow(ok=False)
            self._active_wf_row = None
            self._active_bot_row = None
            self._active_log_row = None
            if answer:
                self.chat.add_bubble("pill", ("✖ " + answer[:160], "err"))
            self._set_busy(False, hud_state="idle", status_text="Idle")
            self.input.setFocus()
            return

        if self._active_bot_row is not None:
            if answer and len(answer) > len(self._stream_buf):
                self._active_bot_row.update_content(answer)
            self._switch_phase("idle")
            self._finalize_workflow(ok=True)
            self._active_wf_row = None
            self._active_bot_row = None
            self._active_log_row = None
            self._set_busy(False, hud_state="idle", status_text="Idle")
            self.input.setFocus()
        elif answer:
            self._switch_phase("generating")
            self._set_busy(False, hud_state="generating", status_text="Processing")
            self._start_token_stream(answer)
        else:
            self._switch_phase("idle")
            self._finalize_workflow(ok=True)
            self._active_wf_row = None
            self._active_log_row = None
            self._set_busy(False, hud_state="idle", status_text="Idle")
            self.input.setFocus()

    def _on_ask(self, kind, text, holder):
        self.raise_()
        self.activateWindow()
        try:
            if kind == "confirm":
                box = QMessageBox(self)
                box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
                box.setIcon(QMessageBox.Icon.Warning)
                box.setWindowTitle("Infinity")
                box.setText(text)
                box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                box.setDefaultButton(QMessageBox.StandardButton.No)
                holder.value = box.exec() == QMessageBox.StandardButton.Yes
            else:
                dlg = QInputDialog(self)
                dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
                dlg.setWindowTitle("Infinity")
                dlg.setLabelText(text)
                ok = dlg.exec()
                holder.value = dlg.textValue().strip() if ok else ""
        finally:
            holder.ev.set()

    # ---- worker thread
    def _agent_event(self, kind, data):
        self.bridge.event.emit(self._cur_id, kind, str(data))

    def _ask_from_worker(self, kind, text):
        h = _Holder()
        self.bridge.ask.emit(kind, text, h)
        while not h.ev.wait(0.2):
            pass
        return h.value

    def _run_command(self, line):
        emit = lambda s: self.bridge.event.emit(self._cur_id, "log", s)
        import contextlib
        w = _EmitWriter(emit)
        with contextlib.redirect_stdout(w):
            res = self.commands(line, self.agent, True)
        w.flush()
        return res

    def _worker(self):
        self._worker_tid = threading.get_ident()
        try:
            from core import safety
        except Exception:
            safety = None
        try:
            import tools
        except Exception:
            tools = None
        while True:
            try:
                jid, text = self._jobs.get()
                with self._busy_lock:
                    self._worker_busy = True
                    self._cur_id = jid
                if safety:
                    safety.clear_kill()
                if tools:
                    tools.STATE.pop("abort", None)
                snap = len(getattr(self.agent, "messages", []) or [])
                answer, ok = "", True
                try:
                    handled = None
                    if text.startswith("/") and self.commands:
                        handled = self._run_command(text)
                    if handled == "exit":
                        QTimer.singleShot(0, self.close)
                    elif handled:
                        if text.strip() in ("/reset", "/clear", "/del"):
                            QTimer.singleShot(0, self.chat.clear_all)
                    else:
                        answer = self.agent.run(text) or "Done."
                except AgentStopped:
                    self._rollback(snap)
                    answer, ok = "", True
                except Exception as e:
                    self._rollback(snap)
                    answer, ok = f"Error: {e}", False
                finally:
                    with self._busy_lock:
                        self._worker_busy = False
                self.bridge.done.emit(jid, answer, ok)
            except AgentStopped:
                with self._busy_lock:
                    self._worker_busy = False
                continue

    def _rollback(self, n):
        try:
            if hasattr(self.agent, "messages") and n:
                del self.agent.messages[n:]
        except Exception:
            pass


# ----------------------------------------------------------------- entry
def run(agent, commands=None):
    """Create the Glass GUI and block until it closes. `commands(line, agent, gui)` handles /slash lines."""
    ok, why = available()
    if not ok:
        raise GlassUnavailable(why)
    try:
        app = QApplication.instance() or QApplication(sys.argv[:1])
        app.setStyle("Fusion")
        app.setStyleSheet(f"QDialog, QMessageBox, QInputDialog {{ background:#101935; color:{TXT}; }}"
                          f"QLabel {{ color:{TXT}; }} QLineEdit {{ background:#09122b; color:{TXT}; "
                          f"border:1px solid {BORDER}; padding:4px; }} QPushButton {{ background:#1e3a8a; "
                          f"color:{TXT}; border:1px solid {CYAN}; padding:4px 14px; border-radius:10px; }}")
        win = GlassWindow(agent, commands)
        win.show()
    except Exception as e:
        raise GlassUnavailable(str(e))

    try:
        from core import desktop
        desktop._terminal = int(win.winId())
        _orig_return = desktop.return_to_terminal
        desktop.return_to_terminal = lambda *a, **k: None if win._busy else _orig_return(*a, **k)
        desktop.minimize_terminal = lambda *a, **k: None   # stay on top while skills run
    except Exception:
        pass
    try:
        import tools
        tools.control.set_handlers(
            ask=lambda q: win._ask_from_worker("ask", q) or "",
            confirm=lambda m: bool(win._ask_from_worker("confirm", m)),
        )
    except Exception:
        pass
    return app.exec()