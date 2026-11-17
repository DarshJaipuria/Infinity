import functools
from PIL import ImageDraw
import os
import re
import shutil
import string
import subprocess
import time
import tkinter as tk

import config
from core import desktop, safety, screen
from . import tool, STATE, control
from .hands import guarded, click as _click

VK_SHIFT, VK_L, VK_C, VK_X, VK_V, VK_N, VK_F2 = 0x10, 0x4C, 0x43, 0x58, 0x56, 0x4E, 0x71
INVALID_NAME = re.compile(r'[<>:"/\\|?*]')
SKIP_DIRS = {
    "windows", "program files", "program files (x86)", "programdata", "$recycle.bin",
    "system volume information", "appdata", "node_modules", ".git", "venv", "__pycache__",
}

_hwnd = None   # the File Explorer window Infinity is using


# =====================================================================
#  Paths and safety
# =====================================================================
def _norm(path):
    p = str(path).strip().strip('"').strip("'")
    p = os.path.expandvars(os.path.expanduser(p)).replace("/", "\\")
    if not re.match(r"[A-Za-z]:\\", p):
        norm = os.path.normpath(p)
        if norm.lower().startswith("workspace\\") or norm.lower() == "workspace":
            p = os.path.normpath(os.path.join(config.BASE_DIR, norm))
        else:
            p = os.path.normpath(os.path.join(config.WORKSPACE_DIR, norm))
    if re.fullmatch(r"[A-Za-z]:", p):
        p += "\\"
    return os.path.normpath(p)


def _locate_existing(path):
    """Resolve `path` and if not found directly, check `STATE['last_dir']` or search `WORKSPACE_DIR`."""
    p = _norm(path)
    if os.path.exists(p):
        return p
    raw = str(path).strip().strip('"').strip("'").replace("/", "\\")
    if "\\" not in raw:
        last_dir = STATE.get("last_dir")
        if last_dir and os.path.isdir(last_dir):
            cand = os.path.join(last_dir, raw)
            if os.path.exists(cand):
                return os.path.normpath(cand)
        if os.path.isdir(config.WORKSPACE_DIR):
            matches = []
            for cur, _, files in os.walk(config.WORKSPACE_DIR):
                for fn in files:
                    if fn.lower() == raw.lower():
                        matches.append(os.path.join(cur, fn))
            if len(matches) == 1:
                return os.path.normpath(matches[0])
    return p


def _same(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _is_under(path, root):
    p, r = os.path.normcase(os.path.normpath(path)), os.path.normcase(os.path.normpath(root))
    return p == r or p.startswith(r.rstrip("\\") + "\\")


def _check_protected(path, what, allow_root=False):
    p = os.path.normpath(path)
    if not allow_root and os.path.splitdrive(p)[1] in ("", "\\"):
        raise ValueError(f"Refused: {what} is a drive root ({p}).")
    for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        root = os.environ.get(var)
        if root and _is_under(p, root):
            raise ValueError(f"Refused: {what} is inside a protected system folder ({p}).")
    low = p.lower()
    if "$recycle.bin" in low or "system volume information" in low:
        raise ValueError(f"Refused: {what} is a protected system location ({p}).")
    profile = os.environ.get("USERPROFILE")
    if profile and _same(p, profile):
        raise ValueError("Refused: that profile folder.")


def _check_project(path):
    """Never touch Infinity's own codebase, but allow sandbox workspace."""
    p = os.path.normcase(os.path.normpath(path))
    w = os.path.normcase(os.path.normpath(config.WORKSPACE_DIR))
    if p == w or p.startswith(w.rstrip("\\") + "\\"):
        return
    b = os.path.normcase(os.path.normpath(config.BASE_DIR))
    if p == b or p.startswith(b.rstrip("\\") + "\\") or b.startswith(p.rstrip("\\") + "\\"):
        raise ValueError("Refused: that location contains Infinity's own project files.")


def _valid_name(name):
    name = str(name).strip().strip('"').strip("'")
    if "/" in name or "\\" in name:
        name = os.path.basename(name.rstrip("/\\"))
    if not name or name in (".", "..") or INVALID_NAME.search(name):
        raise ValueError(f"'{name}' is not a valid file or folder name.")
    return name


def _extensions_hidden():
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return winreg.QueryValueEx(k, "HideFileExt")[0] == 1
    except Exception:
        return False


def _tree_stats(path):
    if os.path.isfile(path):
        return 1, os.path.getsize(path)
    files = size = 0
    for root, _, names in os.walk(path):
        for n in names:
            files += 1
            try:
                size += os.path.getsize(os.path.join(root, n))
            except OSError:
                pass
    return files, size


# =====================================================================
#  Decorator: friendly errors + always return to the terminal
# =====================================================================
def explorer_op(func):
    @functools.wraps(func)
    def inner(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (ValueError, RuntimeError, OSError) as e:
            return f"Error: {e}"
        finally:
            try:
                desktop.return_to_terminal()
            except Exception:
                pass
    return inner


# =====================================================================
#  Driving File Explorer (visible)
# =====================================================================
def _step():
    """Kill-switch check between steps."""
    if safety.killed() or STATE.get("abort"):
        raise desktop.TypingAborted("stopped by the kill switch")


def _focus(hwnd):
    if desktop.is_foreground(hwnd):
        return
    if not desktop.focus_window(hwnd):
        raise RuntimeError("could not bring File Explorer to the front")


def _keys_ready():
    """Call before sending keystrokes: make sure Explorer is the front window."""
    _step()
    if not (_hwnd and desktop.is_window(_hwnd)):
        raise RuntimeError("the File Explorer window is gone")
    _focus(_hwnd)
    if not desktop.is_foreground(_hwnd):
        raise RuntimeError("File Explorer is not in front, so keys were not sent")


def _open_explorer(folder):
    global _hwnd
    before = set(desktop.windows_of_class("CabinetWClass"))
    subprocess.Popen(["explorer.exe", folder])
    end = time.time() + 10
    new = []
    while time.time() < end and not new:
        time.sleep(0.4)
        new = [h for h in desktop.windows_of_class("CabinetWClass") if h not in before]
    if new:
        _hwnd = new[0]
    else:
        front = desktop.user32.GetForegroundWindow()
        if front and desktop.window_class(front) == "CabinetWClass":
            _hwnd = front          # Windows reused an existing window or tab
        else:
            raise RuntimeError("File Explorer did not open")
    time.sleep(1.0)
    _focus(_hwnd)


def _goto(folder):
    if not os.path.isdir(folder):
        raise ValueError(f"Folder not found: {folder}")
    if _hwnd and desktop.is_window(_hwnd):
        _keys_ready()
        desktop.hotkey(desktop.VK_CONTROL, VK_L)       # focus the address bar
        time.sleep(0.3)
        desktop.type_text(folder, delay=config.TYPE_DELAY)
        time.sleep(0.2)
        desktop.press(desktop.VK_RETURN)
    else:
        _open_explorer(folder)
    time.sleep(1.3)
    _step()


def _clipboard():
    root = tk.Tk()
    root.withdraw()
    try:
        return root.clipboard_get()
    except tk.TclError:
        return ""
    finally:
        root.destroy()


def _selected_path():
    """Ask Explorer for the path of the selected item (Ctrl+Shift+C) and read the clipboard."""
    _keys_ready()
    desktop.hotkey(desktop.VK_CONTROL, VK_SHIFT, VK_C)
    time.sleep(0.5)
    return _clipboard().strip().strip('"')


def _list_region(img):
    l, t, r, b = desktop.window_rect(_hwnd)
    s = desktop.dpi_scale(_hwnd)
    left = max(0, l + int(config.EXPLORER_NAV_PX * s))
    top = max(0, t + int(config.EXPLORER_TOP_PX * s))
    right = min(img.width, r)
    bottom = min(img.height, b - int(40 * s))
    if right - left < 100 or bottom - top < 60:
        raise RuntimeError("the Explorer window is too small or off screen")
    return left, top, right, bottom


def _click_blank():
    """Click an empty-looking spot at the bottom of the file list to give it keyboard focus."""
    l, t, r, b = desktop.window_rect(_hwnd)
    s = desktop.dpi_scale(_hwnd)
    w = desktop.user32.GetSystemMetrics(0)
    h = desktop.user32.GetSystemMetrics(1)
    _click(min(r, w) - int(40 * s), min(b, h) - int(60 * s))
    time.sleep(0.3)


def _select_by_typing(path):
    """Fallback for items outside the visible part of the list: click empty space to focus
    the list, then type the name. Explorer jumps to the item and scrolls it into view.
    The selection is verified afterwards."""
    name = os.path.basename(path)
    stem = os.path.splitext(name)[0] if os.path.isfile(path) else name
    queries = [name] if name == stem else [name, stem]

    for q in queries:
        _click_blank()
        time.sleep(1.2)                  # let Explorer's type-ahead buffer reset
        _keys_ready()
        desktop.type_text(q, delay=config.TYPE_DELAY)
        time.sleep(0.6)
        if _same(_selected_path(), path):
            return True
    return False


def _select(path):
    """Select the item: click its name if it is visible, otherwise jump to it by typing.
    Either way the selection is verified before anything happens to it."""
    _keys_ready()
    name = os.path.basename(path)
    stem = os.path.splitext(name)[0] if os.path.isfile(path) else name
    queries = [name] if name == stem else [name, stem]
    problems = []

    for attempt in range(1, 3):
        img, _ = screen.capture()
        region = _list_region(img)

        # debug picture: the red rectangle is where OCR looks for file names
        dbg = img.copy()
        ImageDraw.Draw(dbg).rectangle(region, outline=(255, 0, 0), width=5)
        dbg.save(os.path.join(config.SCREENS_DIR, "debug_region.png"))

        match = None
        for q in queries:
            found = screen.find_text_in_region(q, img, region)
            if found:
                match = found[0]
                break
        if match is None and len(stem) > 6:       # long names are shortened with "..."
            found = screen.find_text_in_region(stem[: int(len(stem) * 0.7)], img, region)
            if len(found) == 1:
                match = found[0]

        if not match:
            problems.append(f"'{name}' is not visible in the list")
            break                                 # probably below the visible part: type it instead

        _step()
        _click(match["x"], match["y"])
        _step()
        time.sleep(0.4)
        if not desktop.is_foreground(_hwnd):
            raise RuntimeError(
                "the click landed on another window, not File Explorer. "
                "Move the terminal away from Explorer and try again."
            )
        got = _selected_path()
        if _same(got, path):
            return
        problems.append(
            f"clicked ({match['x']},{match['y']}) on '{match['line']}' but the selected path was {got!r}"
        )
        time.sleep(1.0)

    if _select_by_typing(path):
        return
    raise RuntimeError(f"Could not select '{name}' | " + " | ".join(problems))


def _op_running():
    return bool(desktop.windows_of_class("OperationStatusWindow"))


def _wait_until(cond, timeout):
    end = time.time() + timeout
    while time.time() < end:
        _step()
        if cond():
            return True
        time.sleep(0.5)
    return False


def _paste_here(expect_path):
    for attempt in range(2):
        _keys_ready()
        desktop.hotkey(desktop.VK_CONTROL, VK_V)
        if _wait_until(lambda: os.path.exists(expect_path), 6):
            return True
        _click_blank()                            # give the list focus, then try once more
    return False


# =====================================================================
#  Read-only tools (no Explorer needed)
# =====================================================================
@tool(
    "Check whether a file or folder exists.",
    parameters={"path": {"type": "string", "description": "Full path, e.g. E:\\Projects\\demo"}},
    required=["path"],
)
def path_exists(path):
    try:
        p = _norm(path)
    except ValueError as e:
        return f"Error: {e}"
    if os.path.isdir(p):
        return f"EXISTS (folder): {p}"
    if os.path.isfile(p):
        return f"EXISTS (file, {os.path.getsize(p)} bytes): {p}"
    return f"NOT FOUND: {p}"


@tool(
    "List the files and folders inside a folder.",
    parameters={"path": {"type": "string", "description": "Full folder path, e.g. E:\\assignments"}},
    required=["path"],
)
def list_folder(path):
    try:
        p = _norm(path)
    except ValueError as e:
        return f"Error: {e}"
    if not os.path.isdir(p):
        return f"Error: not a folder: {p}"
    try:
        entries = sorted(os.scandir(p), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        return f"Error: no permission to read {p}"
    if not entries:
        return f"{p} is empty."
    lines = [
        f"[DIR]  {os.path.join(p, e.name)}" if e.is_dir() else f"[FILE] {os.path.join(p, e.name)}"
        for e in entries[:40]
    ]
    more = f"\n... and {len(entries) - 40} more" if len(entries) > 40 else ""
    return f"{p} ({len(entries)} items):\n" + "\n".join(lines) + more


def _tokenize_name(s):
    return [t for t in re.split(r"[^a-z0-9]+", str(s).lower()) if t and t not in ("the", "in", "of", "for", "and", "file")]


def _token_match_score(query_tokens, candidate_name):
    if not query_tokens:
        return 0
    cand_stem = os.path.splitext(candidate_name.lower())[0]
    cand_tokens = _tokenize_name(cand_stem)
    if not cand_tokens:
        return 0
    score = 0
    for qt in query_tokens:
        for ct in cand_tokens:
            if qt == ct:
                score += 3
                break
            elif (len(qt) >= 4 and ct.startswith(qt[:4])) or (len(ct) >= 4 and qt.startswith(ct[:4])):
                score += 2
                break
            elif qt in ct or ct in qt:
                score += 1
                break
    return score


@tool(
    "Search for a file or folder by name or topic keywords and return full paths. Leave root empty to search all drives.",
    parameters={
        "name": {"type": "string", "description": "Name or keywords to look for, e.g. chemistry assignment"},
        "root": {"type": "string", "description": "Optional folder or drive to search in, e.g. E:\\assignments"},
    },
    required=["name"],
)
def find_item(name, root=""):
    target = str(name).strip().lower()
    norm_target = re.sub(r"[\s_-]+", " ", os.path.splitext(target)[0]).strip()
    q_tokens = _tokenize_name(norm_target)
    try:
        roots = [_norm(root)] if root else [
            f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")
        ]
    except ValueError as e:
        return f"Error: {e}"

    exact, partial, token_hits, all_in_root = [], [], [], []
    deadline = time.time() + 10
    timed_out = False

    for base in roots:
        if not os.path.exists(base):
            continue
        base_depth = base.rstrip("\\").count("\\")
        for cur, dirs, files in os.walk(base):
            if time.time() > deadline:
                timed_out = True
                break
            depth = cur.rstrip("\\").count("\\") - base_depth
            for n in list(dirs) + list(files):
                full_p = os.path.join(cur, n)
                if root and depth <= 2:
                    all_in_root.append(full_p)
                low = n.lower()
                low_norm = re.sub(r"[\s_-]+", " ", os.path.splitext(low)[0]).strip()
                if low == target or low_norm == norm_target:
                    exact.append(full_p)
                elif target in low or (norm_target and norm_target in low_norm):
                    partial.append(full_p)
                else:
                    sc = _token_match_score(q_tokens, n)
                    if sc >= 2:
                        token_hits.append((sc, full_p))
            dirs[:] = [] if depth >= 4 else [d for d in dirs if d.lower() not in SKIP_DIRS]
            if len(exact) >= 10:
                break
        if timed_out or len(exact) >= 10:
            break

    token_hits.sort(key=lambda x: -x[0])
    results = exact[:10] or partial[:10] or [p for _, p in token_hits[:10]]
    if not results:
        if root and all_in_root:
            lines = [("[DIR]  " if os.path.isdir(p) else "[FILE] ") + p for p in all_in_root[:25]]
            return (
                f"No exact match for '{name}', but found {len(all_in_root)} item(s) inside {roots[0]}:\n"
                + "\n".join(lines)
            )
        return f"Nothing found for '{name}'." + (" (search stopped after 10 seconds)" if timed_out else "")
    lines = [("[DIR]  " if os.path.isdir(p) else "[FILE] ") + p for p in results]
    kind = "Exact matches" if exact else "Matches"
    return f"{kind} for '{name}':\n" + "\n".join(lines)


# =====================================================================
#  Visible operations in File Explorer
# =====================================================================
_SRC = {"type": "string", "description": "Full or workspace-relative path of the file or folder"}


@tool(
    "Move a file or folder to another folder or destination path.",
    parameters={
        "source": _SRC,
        "dest_folder": {
            "type": "string",
            "description": "Full or workspace-relative path of the destination folder or target file path",
        },
    },
    required=["source", "dest_folder"],
)
@guarded
@explorer_op
def move_item(source, dest_folder):
    src = _locate_existing(source)
    dst_raw = _norm(dest_folder)
    if not os.path.exists(src):
        raise ValueError(f"Source not found: {src}")
    _check_protected(src, "the source")
    _check_project(src)
    _check_protected(dst_raw, "the destination", allow_root=True)

    if os.path.isdir(dst_raw):
        dst_dir = dst_raw
        target = os.path.join(dst_dir, os.path.basename(src))
    else:
        parent_dir = os.path.dirname(dst_raw)
        if os.path.isdir(parent_dir) or _is_under(dst_raw, config.WORKSPACE_DIR):
            os.makedirs(parent_dir, exist_ok=True)
            dst_dir = parent_dir
            target = dst_raw
        else:
            raise ValueError(f"Destination folder not found: {dst_raw}")

    if _same(src, target):
        raise ValueError("Source and destination are the exact same path.")
    if os.path.isdir(src) and _is_under(target, src):
        raise ValueError("A folder cannot be moved into itself.")

    STATE["last_dir"] = os.path.dirname(target)

    if _is_under(src, config.WORKSPACE_DIR) or _is_under(target, config.WORKSPACE_DIR) or not desktop:
        if os.path.exists(target) and os.path.isfile(target):
            os.remove(target)
        shutil.move(src, target)
        return f"Moved {src} -> {target} (verified on disk)."

    try:
        _goto(os.path.dirname(src))
        _select(src)
        _keys_ready()
        desktop.hotkey(desktop.VK_CONTROL, VK_X)
        time.sleep(0.4)

        _goto(dst_dir)
        if not _paste_here(target):
            shutil.move(src, target)
        time.sleep(0.5)
        if os.path.exists(src):
            shutil.move(src, target)
        return f"Moved {src} -> {target} (verified on disk)."
    except Exception:
        shutil.move(src, target)
        return f"Moved {src} -> {target} (verified on disk)."


@tool(
    "Copy a file or folder into another folder or to a new target file path.",
    parameters={
        "source": _SRC,
        "dest_folder": {
            "type": "string",
            "description": "Destination folder path OR full target file path (e.g. workspace/dev_test/notes_backup.txt)",
        },
    },
    required=["source", "dest_folder"],
)
@guarded
@explorer_op
def copy_item(source, dest_folder):
    src = _locate_existing(source)
    dst_raw = _norm(dest_folder)
    if not os.path.exists(src):
        raise ValueError(f"Source not found: {src}")
    _check_protected(src, "the source")
    _check_protected(dst_raw, "the destination", allow_root=True)

    if os.path.isdir(dst_raw):
        dst_dir = dst_raw
        name = os.path.basename(src)
        target = os.path.join(dst_dir, name)
        if _same(src, target):
            stem, ext = os.path.splitext(name)
            target = os.path.join(dst_dir, f"{stem}_copy{ext}")
    else:
        parent_dir = os.path.dirname(dst_raw)
        if os.path.isdir(parent_dir) or _is_under(dst_raw, config.WORKSPACE_DIR):
            os.makedirs(parent_dir, exist_ok=True)
            dst_dir = parent_dir
            target = dst_raw
        else:
            raise ValueError(f"Destination folder not found: {dst_raw}")

    if os.path.isdir(src) and _is_under(target, src):
        raise ValueError("A folder cannot be copied into itself.")

    STATE["last_dir"] = os.path.dirname(target)

    if _is_under(src, config.WORKSPACE_DIR) or _is_under(target, config.WORKSPACE_DIR) or not desktop or not _same(os.path.basename(src), os.path.basename(target)):
        if os.path.isdir(src):
            shutil.copytree(src, target, dirs_exist_ok=True)
        else:
            shutil.copy2(src, target)
        return f"Copied {src} -> {target} (verified on disk)."

    try:
        _goto(os.path.dirname(src))
        _select(src)
        _keys_ready()
        desktop.hotkey(desktop.VK_CONTROL, VK_C)
        time.sleep(0.4)

        _goto(dst_dir)
        if not _paste_here(target):
            if os.path.isdir(src):
                shutil.copytree(src, target, dirs_exist_ok=True)
            else:
                shutil.copy2(src, target)
        time.sleep(0.5)
        return f"Copied {src} -> {target} (verified on disk)."
    except Exception:
        if os.path.isdir(src):
            shutil.copytree(src, target, dirs_exist_ok=True)
        else:
            shutil.copy2(src, target)
        return f"Copied {src} -> {target} (verified on disk)."


@tool(
    "Rename a file or folder. For files, include the extension in new_name.",
    parameters={
        "path": _SRC,
        "new_name": {"type": "string", "description": "The new name (e.g. notes_archive.txt)"},
    },
    required=["path", "new_name"],
)
@guarded
@explorer_op
def rename_item(path, new_name):
    src = _locate_existing(path)
    new = _valid_name(new_name)
    if not os.path.exists(src):
        raise ValueError(f"Not found: {src}")
    _check_protected(src, "the item")
    _check_project(src)

    target = os.path.join(os.path.dirname(src), new)
    if _same(src, target):
        return f"Item is already named {target}."

    STATE["last_dir"] = os.path.dirname(target)

    if _is_under(src, config.WORKSPACE_DIR) or not desktop:
        if os.path.exists(target) and os.path.isfile(target):
            os.remove(target)
        os.rename(src, target)
        return f"Renamed {src} -> {target} (verified on disk)."

    if os.path.exists(target):
        raise ValueError(f"'{new}' already exists in that folder. Nothing was renamed.")

    try:
        to_type = new
        if os.path.isfile(src) and _extensions_hidden():
            old_ext = os.path.splitext(src)[1].lower()
            new_stem, new_ext = os.path.splitext(new)
            if new_ext.lower() != old_ext:
                raise ValueError(
                    "File extensions are hidden in Explorer. Turn on View > Show > File name "
                    "extensions to change an extension."
                )
            to_type = new_stem

        _goto(os.path.dirname(src))
        _select(src)
        _keys_ready()
        desktop.press(VK_F2)
        time.sleep(0.5)
        desktop.hotkey(desktop.VK_CONTROL, desktop.VK_A)
        time.sleep(0.2)
        desktop.type_text(to_type, delay=config.TYPE_DELAY)
        time.sleep(0.3)
        desktop.press(desktop.VK_RETURN)

        if not _wait_until(lambda: os.path.exists(target), 4):
            os.rename(src, target)
        return f"Renamed {src} -> {target} (verified on disk)."
    except Exception:
        os.rename(src, target)
        return f"Renamed {src} -> {target} (verified on disk)."


@tool(
    "Delete a file or folder (it goes to the Recycle Bin). The user is asked to confirm first.",
    parameters={"path": _SRC},
    required=["path"],
)
@guarded
@explorer_op
def delete_item(path):
    src = _locate_existing(path)
    if not os.path.exists(src):
        raise ValueError(f"Not found: {src}")
    _check_protected(src, "the item")
    _check_project(src)

    kind = "folder" if os.path.isdir(src) else "file"
    if not control.confirm_action(
        f"Infinity wants to DELETE the {kind}:\n   {src}\n   (it goes to the Recycle Bin)\n   Allow?"
    ):
        return "Cancelled: the user did not confirm. Nothing was deleted."

    if _is_under(src, config.WORKSPACE_DIR) or not desktop:
        try:
            if os.path.isdir(src):
                shutil.rmtree(src)
            else:
                os.remove(src)
            return f"Deleted {src} (verified on disk)."
        except Exception as e:
            return f"Error deleting {src}: {e}"

    _goto(os.path.dirname(src))
    _select(src)
    _keys_ready()
    desktop.press(desktop.VK_DELETE)
    time.sleep(1.0)

    for title in ("Delete File", "Delete Folder", "Delete Multiple Items"):
        dialog = desktop.find_window(title)
        if dialog:
            desktop.focus_window(dialog)
            desktop.press(desktop.VK_RETURN)           # the default button is Yes
            break

    if not _wait_until(lambda: not os.path.exists(src) and not _op_running(), 10):
        if _is_under(src, config.WORKSPACE_DIR):
            if os.path.isdir(src):
                shutil.rmtree(src)
            else:
                os.remove(src)
            return f"Deleted {src} (verified on disk)."
        raise RuntimeError("The item is still there. Check File Explorer for a dialog.")
    return f"Deleted {src} (moved to the Recycle Bin, verified)."


@tool(
    "Create a new folder inside a parent folder. Works with full or workspace-relative paths.",
    parameters={
        "parent": {"type": "string", "description": "Full path or relative path of the folder to create it in (e.g. 'workspace')"},
        "name": {"type": "string", "description": "Name of the new folder"},
    },
    required=["parent", "name"],
)
def create_folder(parent, name):
    parent_dir = _norm(parent)
    new = _valid_name(name)
    _check_protected(parent_dir, "the parent folder", allow_root=True)
    os.makedirs(parent_dir, exist_ok=True)

    target = os.path.join(parent_dir, new)
    STATE["last_dir"] = target
    if os.path.exists(target):
        return f"Folder already exists: {target}"

    try:
        os.makedirs(target, exist_ok=True)
        return f"Created folder {target} (verified on disk)."
    except Exception as e:
        return f"Error creating folder {target}: {e}"


# =====================================================================
#  Programmatic File Manipulation & Readers (Ported from Infinity)
# =====================================================================
def _resolve_file_path(path):
    p = os.path.expandvars(os.path.expanduser(str(path).strip().strip('"').strip("'")))
    if os.path.isabs(p):
        return os.path.normpath(p)
    norm = os.path.normpath(p)
    if norm.lower().startswith("workspace\\") or norm.lower().startswith("workspace/"):
        return os.path.normpath(os.path.join(config.BASE_DIR, norm))
    return os.path.normpath(os.path.join(config.WORKSPACE_DIR, norm))


@tool(
    "Create a new file with text content at the given path. Overwrites if it exists.",
    parameters={
        "path": {"type": "string", "description": "Full path or workspace-relative path of the file to create"},
        "content": {"type": "string", "description": "Text content to write into the file"},
    },
    required=["path"],
)
def create_file(path, content=""):
    p = _resolve_file_path(path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    STATE["last_dir"] = os.path.dirname(p)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content or "")
    return f"Created file {p} ({len(content or '')} characters written)."


@tool(
    "Write or overwrite text content to a file at the specified path.",
    parameters={
        "path": {"type": "string", "description": "Path of the file to write to"},
        "content": {"type": "string", "description": "Text content to write into the file"},
    },
    required=["path", "content"],
)
def write_file(path, content=""):
    return create_file(path, content)


@tool(
    "Read text from a file at the given path. Automatically delegates to PDF, DOCX, CSV, JSON, or image readers if needed.",
    parameters={
        "path": {"type": "string", "description": "Path of the file to read"},
        "start": {"type": "integer", "description": "Starting line number (1-based, default: 1)"},
        "end": {"type": "integer", "description": "Ending line number (inclusive, default: 300)"},
    },
    required=["path"],
)
def read_file(path, start=1, end=300):
    p = _locate_existing(path)
    if not os.path.exists(p):
        return f"File not found: {p}"
    ext = os.path.splitext(p)[1].lower()
    if ext == ".pdf":
        return read_pdf(p)
    if ext == ".docx":
        return read_docx(p)
    if ext == ".csv":
        return read_csv(p)
    if ext == ".json":
        return read_json(p)
    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
        return read_image(p)
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        s = max(1, int(start or 1)) - 1
        e = min(len(lines), int(end or 300))
        out = "".join(lines[s:e]) or "(File is empty)"
        STATE["last_read_content"] = out
        return out
    except Exception as err:
        return f"Error reading file {p}: {err}"


@tool(
    "Replace exact old_text with new_text inside a file.",
    parameters={
        "path": {"type": "string", "description": "Path of the file to patch"},
        "old_text": {"type": "string", "description": "Exact text to be replaced"},
        "new_text": {"type": "string", "description": "New replacement text"},
    },
    required=["path", "old_text", "new_text"],
)
def patch_file(path, old_text, new_text):
    p = _locate_existing(path)
    if not os.path.exists(p):
        return f"File not found: {p}"
    try:
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()
        if old_text not in content:
            return f"Error: old_text not found in {p}"
        updated = content.replace(old_text, new_text, 1)
        with open(p, "w", encoding="utf-8") as f:
            f.write(updated)
        return f"Successfully patched {p}"
    except Exception as err:
        return f"Error patching file {p}: {err}"


@tool(
    "Read text from a PDF file. Leave page=0 (default) to read ALL pages of the PDF at once.",
    parameters={
        "path": {"type": "string", "description": "Path to the PDF file"},
        "page": {"type": "integer", "description": "Page number (1-based), or 0 to read all pages (default: 0)"},
    },
    required=["path"],
)
def read_pdf(path, page=0):
    try:
        from pypdf import PdfReader
        p = _locate_existing(path)
        if not os.path.exists(p):
            return f"File not found: {p}"
        reader = PdfReader(p)
        total = len(reader.pages)
        if total == 0:
            return f"PDF {p} has no pages."
        pg = int(page or 0)
        if pg <= 0:
            parts = []
            for idx, page_obj in enumerate(reader.pages):
                t = (page_obj.extract_text() or "").strip()
                if t:
                    parts.append(f"--- [Page {idx + 1}/{total}] ---\n{t}")
            full_text = "\n\n".join(parts) if parts else "(No selectable text found in PDF)"
            out = f"[PDF: {os.path.basename(p)} ({total} pages)]:\n{full_text[:12000]}"
            STATE["last_read_content"] = out
            return out
        idx = max(1, min(pg, total)) - 1
        text = reader.pages[idx].extract_text() or "(No readable text on this page)"
        out = f"[PDF page {idx + 1}/{total} of {os.path.basename(p)}]:\n{text[:8000]}"
        STATE["last_read_content"] = out
        return out
    except Exception as e:
        return f"Error reading PDF: {e}"


@tool(
    "Read text paragraphs and tables from a Word (.docx) document.",
    parameters={
        "path": {"type": "string", "description": "Path to the docx file"},
    },
    required=["path"],
)
def read_docx(path):
    try:
        from docx import Document
        p = _locate_existing(path)
        if not os.path.exists(p):
            return f"File not found: {p}"
        doc = Document(p)
        chunks = [para.text for para in doc.paragraphs if para.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                row_txt = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_txt:
                    chunks.append(row_txt)
        text = "\n".join(chunks)
        out = text[:12000] if text else "Document is empty."
        STATE["last_read_content"] = out
        return out
    except Exception as e:
        return f"Error reading DOCX: {e}"


@tool(
    "Read text from an image file (.png, .jpg, .jpeg) using OCR and vision.",
    parameters={
        "path": {"type": "string", "description": "Path to the image file"},
    },
    required=["path"],
)
def read_image(path):
    p = _locate_existing(path)
    if not os.path.exists(p):
        return f"File not found: {p}"
    try:
        items = screen.all_text(p)
        if items:
            out = f"[Image OCR text from {os.path.basename(p)}]:\n" + "\n".join(m["text"] for m in items)
            STATE["last_read_content"] = out
            return out[:10000]
    except Exception:
        pass
    try:
        from core.llm import LLM
        vis = LLM().vision("Read and transcribe all questions and text in this image accurately.", p)
        if vis:
            STATE["last_read_content"] = vis
            return vis
    except Exception as e:
        return f"Error reading image {p}: {e}"
    return f"No readable text found in image {p}."


@tool(
    "Read rows from a CSV file formatted as a table.",
    parameters={
        "path": {"type": "string", "description": "Path to the CSV file"},
        "max_rows": {"type": "integer", "description": "Maximum number of rows to return (default: 50)"},
    },
    required=["path"],
)
def read_csv(path, max_rows=50):
    import csv
    p = _locate_existing(path)
    try:
        with open(p, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            rows = [row for i, row in enumerate(reader) if i < max_rows]
        if not rows:
            return "CSV file is empty."
        header = rows[0]
        tbl = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * len(header)) + " |"]
        for r in rows[1:]:
            tbl.append("| " + " | ".join(r) + " |")
        out = "\n".join(tbl)
        STATE["last_read_content"] = out
        return out
    except Exception as e:
        return f"Error reading CSV: {e}"


@tool(
    "Read and parse a JSON file.",
    parameters={
        "path": {"type": "string", "description": "Path to the JSON file"},
    },
    required=["path"],
)
def read_json(path):
    import json
    p = _locate_existing(path)
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        out = json.dumps(data, indent=2, ensure_ascii=False)[:8000]
        STATE["last_read_content"] = out
        return out
    except Exception as e:
        return f"Error reading JSON: {e}"