import os

import config
from tools import STATE
from . import Skill, register

FENCE = "`" * 3

PLAYBOOK = """You are the write_code skill. You build complete programs: console programs, and
single-file tkinter games and GUI apps (with menus, scores, high scores, restart and so on).

STEPS
1. Call build_program exactly once. Pass the user's request in full, with every detail they
   gave (game rules, features, controls, high scores, look).
2. Then call finish with a one-line summary. If build_program returned an Error, call finish
   and report the error in one sentence.

RULES
- Never call build_program twice.
- Do not write any code yourself. build_program writes, tests and fixes the program."""


def finalize(summary):
    build = STATE.get("build")
    if not build:
        return summary

    plan = build["plan"]
    path = build["path"]
    rel = os.path.relpath(path, config.BASE_DIR)
    gui = plan["kind"] == "tkinter"

    lines = [f"✔ Done: {plan['title']}   ({rel})", ""]
    if plan["features"]:
        lines.append("What it does:")
        lines += [f"  • {f}" for f in plan["features"][:10]]
        lines.append("")

    smoke = build["info"].get("smoke")
    console = build["info"].get("console")
    if build["issues"]:
        lines.append(f"⚠ {len(build['issues'])} problem(s) could not be fixed automatically:")
        lines += [f"  - {i.splitlines()[0][:160]}" for i in build["issues"][:3]]
    elif smoke:
        total = sum(smoke.get("actions", {}).values())
        lines.append(f"Tested: auto-play for {smoke.get('seconds', 0)}s with {total} key presses and clicks, no errors.")
    elif console:
        lines.append("Tested: ran it with sample input, no errors.")
        sample = (console.get("output") or "").strip().splitlines()[-3:]
        if sample:
            lines += [f"   > {s[:100]}" for s in sample]
    if build["repairs"]:
        lines.append(f"(fixed automatically {build['repairs']} time(s) during testing)")

    if getattr(config, "SHOW_CODE_IN_TERMINAL", False):
        lines += ["", f"{FENCE}python", build["code"], FENCE]

    lines += ["", "Play it: type /run here, or run:" if gui else "Run it: type /run here, or run:", f"    python {rel}"]
    return "\n".join(lines)


register(
    Skill(
        name="write_code",
        description=(
            "Write a program, script, tool or game and test it automatically. Handles console programs and "
            "single-file tkinter games or GUI apps like snake, tic tac toe, calculators and trackers."
        ),
        playbook=PLAYBOOK,
        tools=["build_program"],
        direct_output=True,
        finalize=finalize,
        max_steps=6,
    )
)
