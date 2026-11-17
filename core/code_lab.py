"""Plans, writes, tests and repairs complete single-file Python programs (console apps and tkinter games)."""
import ast
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time

import config
from core import editor as ed_mod
from core import game_refs

HARNESS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tk_smoke.py")
REPORT_RE = re.compile(r"@@REPORT_START@@(.*?)@@REPORT_END@@", re.S)

GUI_WORDS = re.compile(
    r"\b(gui|window|tkinter|canvas|button|game|snake|tic[\s\-_]?tac[\s\-_]?toe|pong|tetris|flappy|minesweeper|"
    r"2048|breakout|hangman|platformer|maze|racing|arcade|puzzle|chess|sudoku|connect[\s\-_]?four|"
    r"memory game|quiz app|calculator app|clock app|paint app|drawing app|to-?do app)\b", re.I)
SOFT_GUI_WORDS = re.compile(
    r"\b(app|interface|ui|visual|animation|animated|draw|drawing|clicker|stopwatch|clock|timer|dashboard)\b", re.I)
CONSOLE_WORDS = re.compile(r"\b(console|terminal|command[\s\-]?line|cli|text[\s\-]?based)\b", re.I)
REAL_TIME = re.compile(r"snake|pong|flappy|tetris|breakout|racing|asteroids|invaders|dino|runner|platformer|arcade", re.I)
HIGH_SCORE = re.compile(r"high[\s\-_]?scores?|leaderboard|best scores?|top[\s\-_]?\d+ scores?", re.I)
BLOCKED = [
    "os.remove", "os.unlink", "os.rmdir", "os.system", "shutil.rmtree", "subprocess",
    "__import__", "eval(", "exec(", "os.popen",
]
HIGHSCORE_FEATURE = "Persistent top-5 high score table saved to a JSON file next to the script, with player names"


def say(message):
    print(f"   ⋯ {message}", flush=True)


# =====================================================================
#  Prompts
# =====================================================================
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "filename": {"type": "string"},
        "kind": {"type": "string", "enum": ["tkinter", "console"]},
        "features": {"type": "array", "items": {"type": "string"}},
        "test_input": {"type": "string"},
    },
    "required": ["title", "filename", "kind", "features"],
}

PLAN_SYSTEM = """You plan single-file Python programs. Read the request and answer with JSON only.
- title: a short name for the program.
- filename: a snake_case file name ending in .py.
- kind: "tkinter" for anything with a window, buttons, drawing or a game; "console" for text programs that use input() and print().
- features: 8 to 14 short, concrete things the finished program must do. For a game include the exact rules, the controls, scoring, game over detection, restart, a start screen or clear instructions, and a polished look. For a GUI tool list every button and what it does. Include everything the user asked for (for example high scores).
- test_input: only for console programs: the lines a user would type to test the program, one per line. Empty for tkinter."""

RULES = """You are an expert Python programmer who writes complete, polished, working single-file programs.

OUTPUT RULES
- Output ONLY the full Python source code. No explanation before or after it. No markdown fences.
- ONE file. Python 3.10+. Standard library only (tkinter, random, json, os, time, math, ...). No pip packages, no image or sound files, nothing to download.
- It must run immediately with: python file.py. Every feature must be fully implemented: no placeholders, no TODO, no "pass" stubs, no "...".
- Start with a one-line docstring. Add short helpful comments. Use clear names.
- Structure: constants at the top, small helper functions, one class for the app or game, a main() function, and at the bottom: if __name__ == "__main__": main()"""

TK_RULES = """
TKINTER RULES
- import tkinter as tk (and messagebox / simpledialog only if you use them). One window, with a title, resizable(False, False), centered on the screen.
- Real-time games: draw on a tk.Canvas and run the game loop with root.after(delay_ms, self.tick). NEVER use time.sleep(), input() or while-loops that block the window.
- Keep the id that root.after returns and cancel it with root.after_cancel before every restart, so loops never stack up.
- Keyboard: root.bind("<Key>", handler) and read event.keysym.lower() ("up", "down", "left", "right", "w", "a", "s", "d", "space", "return", "p", "r").
- Keep a clear game state ("menu", "playing", "paused", "over") and make every feature really work: start screen, scoring, levels or speed-up, game over, restart, pause.
- Make it look good: dark or soft background, readable fonts like ("Segoe UI", 14, "bold"), colors, a score bar, and nice overlay screens for the menu, pause and game over.
- Turn-based board games: use tk.Button cells or a canvas, detect wins and draws, highlight the winning cells, keep a scoreboard, and offer a new round button."""

HIGHSCORE_RULES = """
HIGH SCORES (required when the user asks for them, and a good idea for any score-based game): save the top 5 as JSON next to the script. Use these helper functions exactly (change the file name in SCORE_FILE to match the game):

SCORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "highscores.json")

def load_scores():
    try:
        with open(SCORE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [(str(n), int(s)) for n, s in data][:5]
    except (OSError, ValueError, TypeError):
        return []

def save_score(name, score):
    scores = load_scores() + [(name, score)]
    scores.sort(key=lambda item: item[1], reverse=True)
    scores = scores[:5]
    try:
        with open(SCORE_FILE, "w", encoding="utf-8") as f:
            json.dump(scores, f)
    except OSError:
        pass
    return scores

def is_high_score(score):
    scores = load_scores()
    return score > 0 and (len(scores) < 5 or score > scores[-1][1])

When a game ends: if is_high_score(score), ask for the name with simpledialog.askstring("New high score!", "Enter your name:", parent=root), then call save_score. Show the top-5 table on the menu screen and on the game over screen."""

CONSOLE_RULES = """
CONSOLE RULES
- A text program: use input() and print(). Validate input: loop until it is valid and never crash on bad input (catch ValueError).
- Print clear prompts and clear results. Show the complete result, not just yes or no.
- Put the logic in functions that return values and call them from main()."""


def system_prompt(plan, request):
    parts = [RULES]
    if plan["kind"] == "tkinter":
        parts.append(TK_RULES)
        if HIGH_SCORE.search(request) or any(HIGH_SCORE.search(f) for f in plan["features"]) or REAL_TIME.search(request):
            parts.append(HIGHSCORE_RULES)
    else:
        parts.append(CONSOLE_RULES)
    return "\n".join(parts)


def generation_prompt(request, plan, reference):
    feats = "\n".join(f"- {f}" for f in plan["features"])
    text = f"Write this program: {request}\n\nProgram name: {plan['title']}\nIt MUST include all of these features:\n{feats}\n"
    if reference:
        text += (
            "\nBelow is a REFERENCE program of a similar kind that works well. Use it as your quality bar and as a "
            "starting structure: keep its good design, and adapt and extend it so the result matches the request above "
            "exactly. Write the complete new file.\n\nREFERENCE PROGRAM:\n" + reference + "\n"
        )
    return text


def repair_prompt(request, plan, code, issues):
    feats = "\n".join(f"- {f}" for f in plan["features"])
    items = "\n".join(f"- {i}" for i in issues[:5])
    return (
        "The program below was tested automatically and has problems. Fix ALL of them and return the COMPLETE "
        "corrected file. Output the code only: no explanations, no markdown fences. Keep everything that already works.\n\n"
        f"ORIGINAL REQUEST: {request}\n\nFEATURES THAT MUST WORK:\n{feats}\n\n"
        f"PROBLEMS FOUND:\n{items}\n\nCURRENT CODE:\n{code}\n"
    )


# =====================================================================
#  Helpers
# =====================================================================
def _code_model():
    return getattr(config, "CODE_MODEL", None)


def _in_thread(fn, ed):
    """Run a blocking call in a thread while keeping the editor window alive."""
    box = {}

    def worker():
        try:
            box["value"] = fn()
        except BaseException as e:      # noqa: BLE001
            box["error"] = e

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    while t.is_alive():
        ed.pump()
        time.sleep(0.03)
    if "error" in box:
        raise box["error"]
    return box.get("value")


def extract_code(text):
    m = re.search(r"```(?:python|py)?[ \t]*\n(.*?)```", text, re.S)
    if m:
        return m.group(1).strip("\n")
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
    if t.endswith("```"):
        t = t[:-3]
    return t.strip("\n")


def normalize_plan(plan, request):
    if not isinstance(plan, dict):
        plan = {}
    title = str(plan.get("title") or "Program").strip()[:60] or "Program"
    base = str(plan.get("filename") or title).lower().replace(".py", "")
    name = re.sub(r"[^a-z0-9_]+", "_", base).strip("_") or "program"
    wants_console = CONSOLE_WORDS.search(request)
    soft_gui = SOFT_GUI_WORDS.search(request)
    # a plain "write a program that..." stays a console program unless the request points to a window
    gui = GUI_WORDS.search(request) or (plan.get("kind") == "tkinter" and soft_gui)
    kind = "tkinter" if (gui and not wants_console) else "console"
    features = [str(f).strip() for f in (plan.get("features") or []) if str(f).strip()][:14]
    if HIGH_SCORE.search(request) and not any(HIGH_SCORE.search(f) for f in features):
        features.append(HIGHSCORE_FEATURE)
    return {
        "title": title, "filename": name + ".py", "kind": kind,
        "features": features, "test_input": str(plan.get("test_input") or ""),
    }


def unique_path(filename):
    os.makedirs(config.WORKSPACE_DIR, exist_ok=True)
    stem, ext = os.path.splitext(filename)
    path = os.path.join(config.WORKSPACE_DIR, filename)
    n = 2
    while os.path.exists(path):
        path = os.path.join(config.WORKSPACE_DIR, f"{stem}_{n}{ext}")
        n += 1
    return path


# =====================================================================
#  Checks
# =====================================================================
def static_issues(code, plan, request):
    issues = []
    low = code.lower()
    for bad in BLOCKED:
        if bad in code:
            issues.append(f"The code uses '{bad}', which is not allowed. Remove it.")
    if re.search(r"^\s*\.\.\.\s*$", code, re.M) or re.search(r"#\s*TODO", code) or "NotImplementedError" in code:
        issues.append("The code contains placeholders (TODO, ..., NotImplementedError). Implement everything fully.")
    if "__main__" not in code:
        issues.append('Missing the entry point: if __name__ == "__main__": main()')
    if plan["kind"] == "tkinter":
        if "tkinter" not in code:
            issues.append("A GUI program must use tkinter.")
        if "mainloop" not in code:
            issues.append("The program never calls root.mainloop(), so no window would stay open.")
        if "time.sleep(" in code:
            issues.append("time.sleep() freezes the window. Use root.after() for timing instead.")
        if re.search(r"(?<![\w.])input\(", code):
            issues.append("input() blocks a GUI program. Use widgets (Entry, Button) instead.")
        if REAL_TIME.search(request) and ".after(" not in code:
            issues.append("A real-time game needs a game loop with root.after(...).")
    wants_scores = HIGH_SCORE.search(request) or any(HIGH_SCORE.search(f) for f in plan["features"])
    if wants_scores and not (("json.dump" in code or ".write(" in code) and "score" in low):
        issues.append("High scores were requested, but the code does not save them to a file. Save the top 5 as JSON next to the script.")
    return issues


def flake_issues(code):
    try:
        from pyflakes.checker import Checker
    except ImportError:
        return []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    found = []
    for m in Checker(tree, "program.py").messages:
        if type(m).__name__ in ("UndefinedName", "UndefinedLocal", "UndefinedExport"):
            found.append(f"line {m.lineno}: {m.message % m.message_args}")
    return found[:6]


def run_smoke(path):
    """Auto-play a tkinter program in a separate process and return the harness report."""
    seconds = getattr(config, "SMOKE_SECONDS", 7)
    try:
        r = subprocess.run(
            [sys.executable, HARNESS, path, str(seconds)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=seconds + 40, cwd=config.WORKSPACE_DIR,
        )
    except subprocess.TimeoutExpired:
        return {"errors": ["The program did not finish the auto-play test in time (blocked?)."], "ok": False}
    m = REPORT_RE.search(r.stdout or "")
    if not m:
        tail = ((r.stderr or "") + (r.stdout or "")).strip()[-1200:]
        return {"errors": [f"The program could not be tested: {tail or 'no output'}"], "ok": False}
    return json.loads(m.group(1))


def run_console(path, test_input):
    text = test_input
    if text and not text.endswith("\n"):
        text += "\n"
    try:
        r = subprocess.run(
            [sys.executable, path], input=text, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=config.RUN_TIMEOUT, cwd=config.WORKSPACE_DIR,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "", "error": f"It ran longer than {config.RUN_TIMEOUT}s (waiting for input forever, or an infinite loop)."}
    output = (r.stdout + r.stderr).strip()
    ok = r.returncode == 0 or "EOFError" in output      # ran out of test input = fine
    return {"ok": ok, "output": output[-1500:], "error": "" if ok else output[-1200:]}


def run_checks(ed, path, code, plan, request):
    """Returns (issues, info). An empty issues list means the program passed."""
    info = {}
    try:
        ast.parse(code)
    except SyntaxError as e:
        lines = code.splitlines()
        line = lines[e.lineno - 1].strip()[:100] if e.lineno and e.lineno <= len(lines) else ""
        return [f"Syntax error on line {e.lineno}: {e.msg}. The line is: {line}"], info

    issues = static_issues(code, plan, request)
    issues += [f"Undefined name, {m}" for m in flake_issues(code)]
    if any("not allowed" in i for i in issues):
        return issues, info                              # never run code that uses forbidden calls

    ed.status("Testing the program...")
    if plan["kind"] == "tkinter":
        ed.hide()
        try:
            report = run_smoke(path)
        finally:
            ed.show()
        info["smoke"] = report
        for err in report.get("errors", []):
            issues.append("Error while the program ran (auto-play test): " + err.strip()[-1200:])
        if not report.get("errors") and report.get("ui_changed") is False:
            issues.append(
                "During the auto-play test (random arrow keys, WASD, space, Enter, R, P, 1-3 and mouse clicks) nothing in "
                "the window ever changed. The controls must visibly work, and the game must start with SPACE, Enter, "
                "a Start button or a click."
            )
    else:
        test_input = plan["test_input"]
        if not test_input and re.search(r"(?<![\w.])input\(", code):
            test_input = "5\n5\n5\n5\n"
        result = run_console(path, test_input)
        info["console"] = result
        if not result["ok"]:
            issues.append("Running it with test input failed: " + result["error"])
    return issues, info


# =====================================================================
#  Writing
# =====================================================================
def stream_code(llm, ed, system, user, label):
    """Let the model write the code, showing every piece in the editor as it arrives."""
    q = queue.Queue()
    stop = threading.Event()

    def worker():
        try:
            for piece in llm.stream_text(
                system, user, temperature=getattr(config, "CODE_TEMPERATURE", 0.3), model=_code_model(),
                think=getattr(config, "CODE_THINK", False), max_tokens=getattr(config, "CODE_MAX_TOKENS", 7000),
            ):
                if stop.is_set():
                    break
                q.put(("text", piece))
            q.put(("done", None))
        except BaseException as e:      # noqa: BLE001
            q.put(("error", e))

    threading.Thread(target=worker, daemon=True).start()
    ed.clear()
    raw, head, head_done = [], "", False
    last_token = last_status = time.time()
    try:
        while True:
            try:
                kind, val = q.get(timeout=0.04)
            except queue.Empty:
                ed.pump()
                if time.time() - last_token > getattr(config, "CODE_IDLE_TIMEOUT", 240):
                    raise RuntimeError("The model stopped responding.")
                continue
            if kind == "error":
                raise RuntimeError(f"The model call failed: {val}")
            if kind == "done":
                break
            last_token = time.time()
            raw.append(val)
            if not head_done:                              # hide a leading ```python fence line
                head += val
                if "\n" not in head and len(head) < 12:
                    continue
                if head.lstrip().startswith("```"):
                    head = head.split("\n", 1)[1] if "\n" in head else ""
                if head:
                    ed.append(head)
                head, head_done = "", True
            else:
                ed.append(val)
            if time.time() - last_status > 0.5:
                last_status = time.time()
                ed.status(f"{label}...  {ed.line_count()} lines")
    except BaseException:
        stop.set()
        raise
    code = extract_code("".join(raw))
    ed.set_text(code)
    return code


def build(llm, request):
    """Plan, write, test and repair a program. Returns a dict describing the result."""
    request = str(request).strip()
    ed = ed_mod.LiveEditor()
    try:
        say("Planning the program...")
        ed.status("Planning the program...")
        raw = _in_thread(
            lambda: llm.plan_json(PLAN_SYSTEM, request, PLAN_SCHEMA, temperature=0.3, model=_code_model()), ed
        )
        try:
            plan = normalize_plan(json.loads(raw), request)
        except (ValueError, TypeError):
            plan = normalize_plan({}, request)

        path = unique_path(plan["filename"])
        open(path, "w", encoding="utf-8").close()
        ed.set_path(path)
        say(f"Writing {os.path.basename(path)} ({plan['kind']}, {len(plan['features'])} features)...")

        system = system_prompt(plan, request)
        reference = game_refs.pick(request)
        code = stream_code(llm, ed, system, generation_prompt(request, plan, reference), "Writing code")
        max_repairs = getattr(config, "CODE_MAX_REPAIRS", 3)

        issues, info, attempts = [], {}, 0
        while True:
            if len(code.strip()) < 40:
                raise RuntimeError("The model did not produce any code.")
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
            say("Testing..." if attempts == 0 else f"Testing the fixed version ({attempts}/{max_repairs})...")
            issues, info = run_checks(ed, path, code, plan, request)
            if not issues or attempts >= max_repairs:
                break
            attempts += 1
            say(f"Found {len(issues)} problem(s). Fixing ({attempts}/{max_repairs}): {issues[0][:90]}")
            fixed = stream_code(
                llm, ed, system, repair_prompt(request, plan, code, issues), f"Fixing (attempt {attempts})"
            )
            if len(fixed.strip()) < 40 or fixed.strip() == code.strip():
                break
            code = fixed

        if issues:
            ed.status(f"Saved with {len(issues)} unresolved problem(s): {os.path.basename(path)}", "#b8860b")
            end = time.time() + getattr(config, "EDITOR_HOLD", 2.0)
            while time.time() < end:
                ed.pump()
                time.sleep(0.05)
        else:
            ed.finish(f"Saved ✔  {path}", hold=getattr(config, "EDITOR_HOLD", 2.0))
        return {"path": path, "code": code, "plan": plan, "issues": issues, "info": info, "repairs": attempts}
    finally:
        ed.close()
