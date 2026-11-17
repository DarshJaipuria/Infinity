import os
import subprocess
import sys

import config
from core import code_lab, editor
from core.llm import LLM
from . import tool, STATE

try:
    from core import desktop   # used only to bring the terminal back to the front
except Exception:
    desktop = None

# Generated code containing these will not be run
BLOCKED = [
    "os.remove", "os.unlink", "os.rmdir", "os.system",
    "shutil.rmtree", "subprocess", "__import__", "eval(", "exec(",
]

_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        _llm = LLM()
    return _llm


def _back_to_terminal():
    if desktop:
        try:
            desktop.return_to_terminal()
        except Exception:
            pass


# =====================================================================
#  The main builder: plans, writes (live in the editor), tests and repairs a program
# =====================================================================
@tool(
    "Write a complete program for the user and test it automatically. Handles console programs "
    "and single-file tkinter games or GUI apps (menus, scores, high scores, restart...). "
    "Pass the user's request in full, with every detail they gave.",
    parameters={
        "request": {
            "type": "string",
            "description": "What to build, in the user's words, including rules, features and controls",
        }
    },
    required=["request"],
)
def build_program(request):
    try:
        result = code_lab.build(_get_llm(), str(request))
    except editor.TypingAborted as e:
        STATE["abort"] = True
        _back_to_terminal()
        return f"Stopped: writing the program was cancelled ({e})."
    except (RuntimeError, OSError) as e:
        _back_to_terminal()
        return f"Error: {e}"

    STATE["last_file"] = result["path"]
    STATE["last_code"] = result["code"]
    STATE["typed"] = True
    STATE["build"] = result
    _back_to_terminal()
    return f"Built {os.path.basename(result['path'])}."


# =====================================================================
#  Older, simpler tools (still available)
# =====================================================================
def _clean(code):
    """Remove markdown fences if the model added them."""
    code = code.strip()
    if code.startswith("```"):
        lines = code.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        code = "\n".join(lines)
    return code


def _safe_name(filename):
    name = os.path.basename(filename)
    if not name.endswith(".py"):
        name += ".py"
    return name


def _write_direct(path, code):
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)


def _type_in_editor(path, code):
    editor.type_into_editor(path, code, delay=config.TYPE_DELAY, hold=config.EDITOR_HOLD)
    _back_to_terminal()


@tool(
    "Save a complete Python program to a file in the workspace.",
    parameters={
        "filename": {"type": "string", "description": "Short file name, e.g. prime_checker.py"},
        "code": {"type": "string", "description": "The complete Python source code"},
    },
    required=["filename", "code"],
)
def save_file(filename, code):
    os.makedirs(config.WORKSPACE_DIR, exist_ok=True)
    name = _safe_name(filename)
    code = _clean(code)
    path = os.path.join(config.WORKSPACE_DIR, name)

    typed = False
    note = ""
    if config.VISIBLE_TYPING:
        try:
            _type_in_editor(path, code)
            typed = True
        except editor.TypingAborted as e:
            _back_to_terminal()
            STATE["abort"] = True
            return f"Stopped: typing was cancelled ({e})."
        except Exception as e:
            note = f" (visible typing failed: {e}; the file was written directly)"

    if not typed:
        _write_direct(path, code)

    STATE["last_file"] = path
    STATE["last_code"] = code
    STATE["typed"] = typed
    STATE.pop("last_run", None)
    return f"Saved {name}.{note} Now test it with run_python."


@tool(
    "Run a saved Python file and return its output. If the program uses input(), "
    "put the test values in test_input, one per line.",
    parameters={
        "filename": {"type": "string", "description": "File name used in save_file"},
        "test_input": {"type": "string", "description": "Text fed to input(), one value per line"},
    },
    required=["filename"],
)
def run_python(filename, test_input=""):
    path = os.path.join(config.WORKSPACE_DIR, _safe_name(filename))
    if not os.path.exists(path):
        return "Error: file not found. Use save_file first."

    with open(path, encoding="utf-8") as f:
        code = f.read()
    for bad in BLOCKED:
        if bad in code:
            return f"Blocked: the code contains '{bad}', which is not allowed. Rewrite without it."

    if test_input and not test_input.endswith("\n"):
        test_input += "\n"

    try:
        r = subprocess.run(
            [sys.executable, path],
            input=test_input,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=config.RUN_TIMEOUT,
            cwd=config.WORKSPACE_DIR,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired:
        return f"Error: program ran longer than {config.RUN_TIMEOUT}s (maybe waiting for input or an infinite loop)."

    output = (r.stdout + r.stderr).strip()[:2000]
    STATE["last_run"] = {"input": test_input.strip(), "output": output, "ok": r.returncode == 0}
    status = "OK" if r.returncode == 0 else f"FAILED (exit code {r.returncode})"
    return f"{status}\nOutput:\n{output or '(no output)'}"


@tool(
    "Validate syntax of a Python, JavaScript, TypeScript, or JSON file before running it.",
    parameters={
        "path": {"type": "string", "description": "Full or workspace-relative path to the file"},
    },
    required=["path"],
)
def check_syntax(path):
    p = os.path.expandvars(os.path.expanduser(str(path).strip().strip('"').strip("'")))
    if not os.path.isabs(p):
        p = os.path.join(config.WORKSPACE_DIR, p)
    if not os.path.exists(p):
        return f"File not found: {p}"
    ext = os.path.splitext(p)[1].lower()
    if ext == ".py":
        try:
            with open(p, "r", encoding="utf-8") as f:
                compile(f.read(), p, "exec")
            return f"Syntax OK for {p}"
        except SyntaxError as e:
            return f"Syntax error in {p} at line {e.lineno}: {e.msg}"
    return f"Syntax check skipped for {ext} (treated as valid)."


@tool(
    "Search for a text pattern or regular expression across files in a directory.",
    parameters={
        "query": {"type": "string", "description": "String or pattern to search for"},
        "path": {"type": "string", "description": "Directory or workspace folder to search (default: workspace)"},
    },
    required=["query"],
)
def grep_search(query, path=""):
    target = os.path.expandvars(os.path.expanduser(str(path or "").strip().strip('"').strip("'")))
    if not target or not os.path.isabs(target):
        target = os.path.join(config.WORKSPACE_DIR, target) if target else config.WORKSPACE_DIR
    if not os.path.exists(target):
        return f"Directory not found: {target}"
    matches = []
    q_low = str(query).lower()
    for root, dirs, files in os.walk(target):
        for f in files:
            fp = os.path.join(root, f)
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as handle:
                    for lno, line in enumerate(handle, 1):
                        if q_low in line.lower():
                            rel = os.path.relpath(fp, target)
                            matches.append(f"{rel}:{lno}: {line.strip()[:120]}")
                            if len(matches) >= 30:
                                break
            except Exception:
                pass
        if len(matches) >= 30:
            break
    if not matches:
        return f"No matches found for '{query}' in {target}"
    return "\n".join(matches)

