import argparse
import json
import os
import re
import subprocess
import sys
import time

import pyautogui

import config
from core import memory, safety
from core.agent import Agent
import skills
import tools

try:
    from core import desktop
except Exception:
    desktop = None


def show_event(kind, data):
    if kind in ("skill_start", "skill_end"):
        print(f"\n{data}")
    else:
        print(f"   ⚙ {data}")


def parse_value(v):
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    try:
        return json.loads(v)
    except ValueError:
        return v


ARG_PATTERN = re.compile(r"""\s*(\w+)=("[^"]*"|'[^']*'|\S+)""")


def parse_do(line):
    """Turn /do tool key=value key="text with spaces" into (tool, args)."""
    parts = line.split(None, 2)
    if len(parts) < 2:
        print('Usage: /do <tool> key=value ...   e.g. /do mouse_move x=500 y=400\n')
        return None

    name = parts[1]
    rest = parts[2] if len(parts) > 2 else ""

    args = {}
    for m in ARG_PATTERN.finditer(rest):
        args[m.group(1)] = parse_value(m.group(2))

    leftover = ARG_PATTERN.sub("", rest).strip()
    if leftover:
        print(f"Could not read: {leftover}")
        print("Use key=value, and put text with spaces inside quotes.\n")
        return None

    if name not in tools.TOOLS:
        print(f"Unknown tool '{name}'. Type /tools to see them.\n")
        return None
    return name, args


def do_command(line):
    parsed = parse_do(line)
    if not parsed:
        return
    name, args = parsed

    safety.clear_kill()
    tools.STATE.pop("abort", None)
    print(f"   ⚙ {name}({args})")
    print(f"   → {tools.run_tool(name, args)}\n")


def demo():
    print("DEMO: click inside any text box (Notepad is fine) and leave the mouse there.")
    print("Starting in 5 seconds. Stop: press Esc, or throw the mouse to the top-left corner.\n")
    for i in range(5, 0, -1):
        print(f"  {i}...")
        time.sleep(1)

    safety.clear_kill()
    tools.STATE.pop("abort", None)

    w, h = pyautogui.size()
    pos = pyautogui.position()
    x = max(10, min(pos.x, w - 200))
    y = max(10, min(pos.y, h - 200))

    steps = [
        ("mouse_move", {"x": x + 150, "y": y}),
        ("mouse_move", {"x": x + 150, "y": y + 150}),
        ("mouse_move", {"x": x, "y": y + 150}),
        ("mouse_move", {"x": x, "y": y}),
        ("click", {}),
        ("type_text", {"text": "Hello from Infinity! Testing autonomous controls...\n"}),
    ]

    for tool_name, args in steps:
        if safety.killed():
            print("Stopped.")
            break
        print(f"   ⚙ {tool_name}({args})")
        tools.run_tool(tool_name, args)
        time.sleep(config.ACTION_DELAY)
    print("Demo complete.\n")


def countdown(msg, seconds=4):
    print(msg)
    for i in range(seconds, 0, -1):
        print(f"  {i}...")
        time.sleep(1)
    p = pyautogui.position()
    print(f"Position: x={p.x}, y={p.y}\n")


def save_workflow_cmd(line, agent):
    parts = line.split(None, 1)
    name = parts[1].strip() if len(parts) > 1 else f"workflow_{int(time.time())}"
    wf_dir = getattr(config, "WORKFLOWS_DIR", os.path.join(config.BASE_DIR, "workflows"))
    os.makedirs(wf_dir, exist_ok=True)
    idx_path = os.path.join(wf_dir, "index.json")

    try:
        with open(idx_path, "r", encoding="utf-8") as f:
            idx = json.load(f)
    except Exception:
        idx = {}

    md_path = os.path.join(wf_dir, f"{name}.md")
    # Generate summary of recent turns
    recent_turns = agent.history.get_messages()
    summary_lines = [f"# Workflow: {name}\n", f"Created: {time.strftime('%Y-%m-%d %H:%M:%S')}\n", "## Execution Log\n"]
    for turn in recent_turns[-6:]:
        role = turn.get("role", "")
        content = turn.get("content", "")
        summary_lines.append(f"- **{role.upper()}**: {content}\n")

    with open(md_path, "w", encoding="utf-8") as f:
        f.writelines(summary_lines)

    idx[name] = f"Workflow generated from session for: {name}"
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(idx, f, indent=4)

    print(f"Saved workflow: {name} -> {md_path}\n")


def handle_command(user, agent, gui=False):
    """Handle /slash commands. Returns None (not a command), "exit", or True."""
    if not user.startswith("/"):
        return None
    cmd = user.strip().lower()

    if cmd in ("/exit", "/bye", "/quit"):
        return "exit"
    if cmd == "/help":
        print("""Available Commands:
  /help                  - Show this help menu
  /tokens                - Display live token usage statistics
  /memory                - View user facts & long-term memory
  /scratchpad            - View active agent scratchpad / checklist
  /tools                 - List all available main skills and tools
  /reset or /clear       - Reset conversation context and start fresh
  /update                - Reload runtime configuration from config.json
  /save_workflow <name>  - Save current turn workflow to workflows/
  /do <tool> key=val     - Directly execute any tool
  /demo                  - Run autonomous control demo
  /run                   - Run the last generated code script
  /pos                   - Inspect current cursor coordinates
  /in <sec> /do ...      - Delay tool execution
  /exit or /bye          - Exit Infinity
""")
        return True
    if cmd in ("/reset", "/clear", "/del"):
        agent.reset()
        print("Conversation context cleared.\n")
        return True
    if cmd == "/tokens":
        print(agent.get_token_stats() + "\n")
        return True
    if cmd == "/memory":
        mem = memory.read_memory()
        print(f"System Memory:\n{mem or '(empty)'}\n")
        return True
    if cmd == "/scratchpad":
        scratch = memory.read_scratchpad()
        print(f"Scratchpad:\n{scratch or '(empty)'}\n")
        return True
    if cmd == "/update":
        config.update_from_json()
        print("Updated configuration from config.json\n")
        return True
    if user.startswith("/save_workflow"):
        save_workflow_cmd(user, agent)
        return True
    if cmd == "/tools":
        print("Main skills:", ", ".join(skills.SKILLS))
        print("Sub-tools:  ", ", ".join(tools.TOOLS), "\n")
        return True
    if cmd == "/pos":
        countdown("Hover over the spot you want (4 seconds)...")
        return True
    if user.startswith("/in "):
        try:
            _, secs, rest = user.split(" ", 2)
            secs = int(secs)
            assert rest.startswith("/do ")
        except (ValueError, AssertionError):
            print("Usage: /in <seconds> /do <tool> key=value ...\n")
            return True
        if parse_do(rest) is None:
            return True
        print(f"Click/switch to the target window now. Running in {secs}s...")
        for i in range(secs, 0, -1):
            print(f"  {i}...")
            time.sleep(1)
        do_command(rest)
        return True
    if cmd == "/demo":
        demo()
        return True
    if user.startswith("/do "):
        do_command(user)
        return True
    if cmd == "/run":
        path = tools.STATE.get("last_file")
        if not path:
            print("Nothing to run yet. Ask me to write some code first.\n")
            return True
        print(f"Running {path}\n" + "-" * 40)
        if gui:
            try:
                r = subprocess.run(
                    [sys.executable, path],
                    cwd=config.WORKSPACE_DIR,
                    text=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=60,
                )
                print(r.stdout or "(no output)")
            except subprocess.TimeoutExpired:
                print("(stopped after 60s)")
        else:
            subprocess.run([sys.executable, path], cwd=config.WORKSPACE_DIR)
        print("-" * 40 + "\n")
        return True

    print(f"Unknown command: {user}. Type /help for available commands.\n")
    return True


def run_cli():
    agent = Agent(on_event=show_event)
    if desktop:
        desktop.remember_terminal()
    print("=" * 60)
    print("Infinity Unified Agent (Ollama + Toolsets)")
    print("Type /help for commands, /exit to quit.")
    print("=" * 60 + "\n")

    while True:
        try:
            user = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user:
            continue

        if desktop:
            desktop.remember_terminal()

        result = handle_command(user, agent)
        if result == "exit":
            break
        if result:
            continue

        answer = agent.run(user)
        print(f"\nInfinity: {answer}\n")


def run_gui():
    """Start the Glass GUI. Returns exit code or None if fallback to CLI."""
    try:
        from ui import glass_gui
    except Exception as e:
        print(f"[Infinity] Glass GUI unavailable ({e}). Falling back to CLI.\n")
        return None

    ok, why = glass_gui.available()
    if not ok:
        print(f"[Infinity] Glass GUI unavailable: {why}. Falling back to CLI.\n")
        return None

    try:
        agent = Agent()
        return glass_gui.run(agent, handle_command) or 0
    except glass_gui.GlassUnavailable as e:
        print(f"[Infinity] Glass GUI failed to start ({e}). Falling back to CLI.\n")
        return None


def main():
    parser = argparse.ArgumentParser(description="Infinity AI agent")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--gui", action="store_true", help="run the Glass GUI (default)")
    mode.add_argument("--cli", action="store_true", help="run the classic terminal interface")
    args = parser.parse_args()

    if not args.cli:
        code = run_gui()
        if code is not None:
            sys.exit(code)
    run_cli()


if __name__ == "__main__":
    main()