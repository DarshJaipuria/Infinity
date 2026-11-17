import functools
import re
import time
import webbrowser

from PIL import ImageDraw

import config
from core import desktop, safety, screen
from . import tool, STATE
from .hands import guarded, click as _click

EMAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[A-Za-z]{2,}$")
BROWSERS = ("chrome", "edge", "firefox", "brave", "opera", "vivaldi")
VK_L = 0x4C


def _back_to_terminal(pause=0.0):
    """Bring the Infinity terminal back to the front (optionally after a short pause)."""
    if not config.GMAIL_RETURN_TO_TERMINAL:
        return
    try:
        time.sleep(pause)
        desktop.return_to_terminal()
    except Exception:
        pass


def gmail_op(func):
    """Turn expected problems into a clear 'Error: ...' message and bring the terminal back."""
    @functools.wraps(func)
    def inner(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (ValueError, RuntimeError, OSError) as e:
            _back_to_terminal()
            return f"Error: {e}"
    return inner


def _step():
    if safety.killed() or STATE.get("abort"):
        raise desktop.TypingAborted("stopped by the kill switch")


# ---------------- which page is the browser showing? ----------------
def _has_browser(title):
    low = title.lower()
    return any(b in low for b in BROWSERS)


def _is_gmail_title(title):
    low = title.lower()
    return _has_browser(title) and any(h in low for h in config.GMAIL_TITLE_HINTS)


def _is_google_home(title):
    return _has_browser(title) and title.lower().startswith("google")


def _wait_for(cond, timeout, interval=0.8):
    end = time.time() + timeout
    while time.time() < end:
        _step()
        if cond():
            return True
        time.sleep(interval)
    return False


def _ready(hwnd, need_gmail=True):
    """Before any click or typing: the same browser window must be in front,
    showing the expected page. Otherwise stop."""
    _step()
    if not desktop.is_foreground(hwnd) and not desktop.focus_window(hwnd):
        raise RuntimeError(
            f"The browser is not the front window. Front window: '{desktop.foreground_title()}'"
        )
    title = desktop.foreground_title()
    ok = _is_gmail_title(title) if need_gmail else (_is_gmail_title(title) or _is_google_home(title))
    if not ok:
        raise RuntimeError(f"The browser is not showing the expected page. Tab title: '{title}'")


# ---------------- looking at the screen ----------------
def _region(hwnd, img, f):
    """A part of the browser window, given as fractions (left, top, right, bottom)."""
    l, t, r, b = desktop.window_rect(hwnd)
    l, t, r, b = max(l, 0), max(t, 0), min(r, img.width), min(b, img.height)
    w, h = r - l, b - t
    return (l + int(w * f[0]), t + int(h * f[1]), l + int(w * f[2]), t + int(h * f[3]))


def _find_in(hwnd, query, fractions, timeout=0):
    """OCR search inside part of the browser window, retrying for `timeout` seconds."""
    end = time.time() + timeout
    while True:
        _step()
        img, _ = screen.capture()
        found = screen.find_text_in_region(query, img, _region(hwnd, img, fractions))
        if found or time.time() >= end:
            return found
        time.sleep(0.8)


def _find_abs(query, region, timeout=0):
    """OCR search inside an absolute screen rectangle (used for the New Message popup)."""
    end = time.time() + timeout
    while True:
        _step()
        img, _ = screen.capture()
        r = (region[0], region[1], min(region[2], img.width), min(region[3], img.height))
        found = screen.find_text_in_region(query, img, r)
        if found or time.time() >= end:
            return found
        time.sleep(0.8)


def _inbox_ready(hwnd):
    if not _is_gmail_title(desktop.foreground_title()):
        return False
    img, _ = screen.capture()
    region = _region(hwnd, img, (0.0, 0.1, 0.5, 0.8))
    return any(screen.find_text_in_region(w, img, region) for w in ("Compose", "Inbox", "Primary"))


def _find_popup(hwnd, timeout):
    """Find the New Message popup (bottom-right). Returns (rectangle, header_y).
    Tries several anchors in case OCR misreads one of them."""
    end = time.time() + timeout
    s = desktop.dpi_scale(hwnd)
    while True:
        _step()
        img, _ = screen.capture()
        area = _region(hwnd, img, (0.4, 0.3, 1.0, 1.0))

        # (text to look for, how far below the popup's title bar that text sits at 100% scaling)
        for query, below_header in (("New Message", 0), ("Recipients", 44), ("Subject", 88)):
            found = screen.find_text_in_region(query, img, area)
            if found:
                a = max(found, key=lambda m: m["y"])          # the popup sits low on the screen
                header_y = a["y"] - int(below_header * s)
                rect = (
                    max(0, a["x"] - int(100 * s)),
                    max(0, header_y - int(40 * s)),
                    img.width,
                    img.height,
                )
                return rect, header_y

        if time.time() >= end:
            seen = [m["line"] for m in screen.find_text_in_region("", img, area)][:10]
            dbg = img.copy()
            ImageDraw.Draw(dbg).rectangle(area, outline=(255, 0, 0), width=5)
            dbg.save(f"{config.SCREENS_DIR}\\debug_gmail.png")
            raise RuntimeError(
                f"The New Message window was not found. OCR saw: {seen}. A picture was saved to "
                "screens\\debug_gmail.png (a black area there means something hid that part of the screen)."
            )
        time.sleep(0.8)


# ---------------- acting ----------------
def _click_at(hwnd, match, need_gmail=False):
    _ready(hwnd, need_gmail=need_gmail)
    _step()
    _click(match["x"], match["y"])
    _step()
    time.sleep(0.5)


def _type(hwnd, text):
    _ready(hwnd)
    desktop.type_text(text, delay=config.GMAIL_TYPE_DELAY)


def _go_to(hwnd, url):
    """Type a web address into the browser's address bar."""
    _ready(hwnd, need_gmail=False)
    desktop.hotkey(desktop.VK_CONTROL, VK_L)
    time.sleep(0.4)
    desktop.type_text(url, delay=0.01)
    time.sleep(0.3)
    desktop.press(desktop.VK_DELETE)       # drop the browser's inline autocomplete suggestion
    desktop.press(desktop.VK_RETURN)


@tool(
    "Prepare an email in Gmail: opens google.com, goes to Gmail, clicks Compose and types the "
    "recipient, subject and body. It does NOT send the email: the user reviews it and clicks Send themselves.",
    parameters={
        "to": {"type": "string", "description": "Recipient email address, e.g. name@example.com"},
        "subject": {"type": "string", "description": "A short, clear subject line"},
        "body": {"type": "string", "description": "The full email text: greeting, message, closing"},
    },
    required=["to", "subject", "body"],
)
@guarded
@gmail_op
def compose_email(to, subject, body):
    recipients = [r.strip() for r in re.split(r"[,;]", str(to)) if r.strip()]
    if not recipients:
        raise ValueError("No recipient given. Ask the user for the email address.")
    bad = [r for r in recipients if not EMAIL.match(r)]
    if bad:
        raise ValueError(f"Not a valid email address: {', '.join(bad)}. Ask the user.")

    subject = " ".join(str(subject).split())                   # one line only
    body = str(body).replace("\r\n", "\n").replace("\\n", "\n").strip()
    if not subject:
        raise ValueError("The subject is empty.")
    if not body:
        raise ValueError("The body is empty.")
    if len(body) > 3000:
        raise ValueError("The body is too long (maximum 3000 characters).")

    # 1. open google.com
    webbrowser.open("https://www.google.com")
    if not _wait_for(lambda: _is_google_home(desktop.foreground_title()), 25):
        raise RuntimeError(
            f"The Google page did not come to the front. Front window: '{desktop.foreground_title()}'"
        )
    hwnd = desktop.user32.GetForegroundWindow()                # remember this browser window
    time.sleep(2.0)                                            # let the page finish drawing

    # 2. click the Gmail link (top right); if it cannot be found, type the address instead
    link = _find_in(hwnd, "Gmail", (0.45, 0.0, 1.0, 0.4), timeout=6)
    if link:
        _click_at(hwnd, link[0])
    else:
        _go_to(hwnd, "https://mail.google.com")

    # 3. wait for the inbox
    if not _wait_for(lambda: _inbox_ready(hwnd), 40):
        raise RuntimeError(
            "The Gmail inbox did not appear. Is the browser signed in to Gmail? "
            f"Tab title: '{desktop.foreground_title()}'"
        )
    time.sleep(1.0)

    # 4. click Compose
    button = _find_in(hwnd, "Compose", (0.0, 0.1, 0.5, 0.8), timeout=6)
    if not button:
        raise RuntimeError(
            "Could not find the Compose button. If Gmail's left menu is collapsed, "
            "expand it with the menu icon and try again."
        )
    _click_at(hwnd, button[0], need_gmail=True)

    # 5. wait for the New Message popup. Everything below only looks inside it.
    popup, header_y = _find_popup(hwnd, 12)
    s = desktop.dpi_scale(hwnd)
    time.sleep(0.8)

    # 6. recipients: type each address, check it appeared, then press Enter.
    #    Enter accepts the matching suggestion and turns the address into a chip,
    #    which also closes the suggestion dropdown that would cover the Subject field.
    field = _find_abs("Recipients", popup, 2)
    if field:
        _click_at(hwnd, field[0], need_gmail=True)

    for address in recipients:
        _type(hwnd, address)
        time.sleep(0.9)
        candidates = [address, address.split("@")[0]]
        if not any(len(c) >= 3 and _find_abs(c, popup, 3) for c in candidates):
            raise RuntimeError(
                "The recipient did not show up in the New Message window, so Infinity stopped before "
                "typing anything else. The window is still open: check it and close it without sending."
            )
        _ready(hwnd)
        desktop.press(desktop.VK_RETURN)
        time.sleep(0.8)

    # 7. subject: find it by OCR; if OCR cannot see it, click where it always is
    spot = _find_abs("Subject", popup, 4)
    if spot:
        _click_at(hwnd, spot[0], need_gmail=True)
    else:
        _click_at(
            hwnd,
            {"x": popup[0] + int(140 * s), "y": header_y + int(88 * s)},
            need_gmail=True,
        )
    _type(hwnd, subject)
    time.sleep(0.4)

    # 8. body (Tab moves from Subject to the message body)
    _ready(hwnd)
    desktop.press(desktop.VK_TAB)
    time.sleep(0.6)
    _type(hwnd, body)
    time.sleep(0.8)

    # 9. check what is visible in the popup (the recipient was already checked)
    first_line = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    subject_ok = bool(_find_abs(subject[:25], popup, 3))
    body_ok = bool(_find_abs(first_line[:25], popup, 3)) if first_line else True
    notes = []
    if not subject_ok:
        notes.append("could not confirm the subject on screen")
    if not body_ok:
        notes.append("could not confirm the start of the body on screen")
    warning = (" WARNING: " + "; ".join(notes) + ". Please check the draft.") if notes else ""

    _back_to_terminal(pause=1.5)       # let the user see the finished draft first

    return (
        f"Email prepared in Gmail and NOT sent. To: {', '.join(recipients)} | Subject: {subject}. "
        f"The user must review it and click Send themselves.{warning}"
    )