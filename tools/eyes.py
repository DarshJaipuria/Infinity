from email.mime import text

from core import screen
from core import desktop
from core.llm import LLM
from . import tool, STATE
from .hands import click as _click

_llm = None


def _vision(prompt, path):
    global _llm
    if _llm is None:
        _llm = LLM()
    return _llm.vision(prompt, screen.shrink(path))


@tool("Take a screenshot of the whole screen and save it to a file.")
def take_screenshot():
    img, path = screen.capture()
    STATE["last_screenshot"] = path
    return f"Screenshot saved: {path} ({img.width}x{img.height})"


@tool("Get the title of the window that is currently in front.")
def get_active_window():
    return desktop.foreground_title() or "(no title)"


@tool("Read ALL visible text on the screen with the position of each line. Slow (a few seconds).")
def read_screen_text():
    _, path = screen.capture()
    items = screen.all_text(path)
    if not items:
        return "No text found on screen."
    lines = [f"({m['x']},{m['y']}) {m['text']}" for m in items[:60]]
    more = f"\n... and {len(items) - 60} more lines" if len(items) > 60 else ""
    return "\n".join(lines) + more


@tool(
    "Find text on the screen (a button, menu item, file name, label) and return its click position.",
    parameters={"text": {"type": "string", "description": "The text to find, e.g. Save"}},
    required=["text"],
)
def find_text_on_screen(text):
    _, path = screen.capture()
    matches = screen.find_text(str(text), path)
    if not matches:
        return f"Not found: '{text}'. Use read_screen_text to see what text is visible."
    lines = [
        f"{i}. '{m['line']}' at x={m['x']}, y={m['y']} (confidence {m['conf']:.2f})"
        for i, m in enumerate(matches[:5], 1)
    ]
    return "\n".join(lines)


@tool(
    "Find text on the screen and left-click it. Use index=2 for the second match, and so on.",
    parameters={
        "text": {"type": "string", "description": "The text to click, e.g. File"},
        "index": {"type": "integer", "description": "Which match to click (default 1)"},
    },
    required=["text"],
)
def click_text(text, index=1):
    if str(text).strip().lower().startswith("send"):
        return "Blocked: Infinity never clicks Send. The user sends emails themselves."
    _, path = screen.capture()
    _, path = screen.capture()
    matches = screen.find_text(str(text), path)
    if not matches:
        return f"Not found: '{text}'. Nothing was clicked."
    i = max(1, int(index)) - 1
    if i >= len(matches):
        return f"Only {len(matches)} match(es) for '{text}'. Nothing was clicked."
    m = matches[i]
    _click(m["x"], m["y"])
    return f"Clicked '{m['line']}' at ({m['x']}, {m['y']})"


@tool(
    "Look at the screen with the vision model and answer a question about it. Slow (several seconds).",
    parameters={"question": {"type": "string", "description": "What to find out about the screen"}},
)
def describe_screen(question="Describe what is on the screen."):
    _, path = screen.capture()
    prompt = (
        "You are looking at a screenshot of a computer screen. "
        f"{question}\n"
        "Be brief and concrete (under 80 words). Mention app names, buttons and text you can read. "
        "A black rectangle is a hidden area, ignore it."
    )
    return _vision(prompt, path)[:600]


@tool(
    "Check something on the screen. Answers YES or NO with a short reason. "
    "Example question: Is the File menu open?",
    parameters={"question": {"type": "string", "description": "A yes/no question about the screen"}},
    required=["question"],
)
def verify_screen(question):
    _, path = screen.capture()
    prompt = (
        "You are looking at a screenshot of a computer screen.\n"
        f"Question: {question}\n"
        "Reply with YES or NO on the first line, then one short sentence explaining what you see. "
        "A black rectangle is a hidden area, ignore it."
    )
    return _vision(prompt, path)[:400]