from . import tool
from core import memory
import utils

try:
    from core import desktop
except Exception:
    desktop = None


def _default_ask(question):
    if desktop:
        desktop.return_to_terminal()
    return input(f"\n? {question}\n   > ").strip()


def _default_confirm(message):
    if desktop:
        desktop.return_to_terminal()
    return input(f"\n!  {message} [y/N]: ").strip().lower() in ("y", "yes")


_handlers = {"ask": _default_ask, "confirm": _default_confirm}


def set_handlers(ask=None, confirm=None):
    """The GUI calls this to show dialogs instead of terminal prompts."""
    if ask:
        _handlers["ask"] = ask
    if confirm:
        _handlers["confirm"] = confirm


def confirm_action(message):
    """Used by dangerous tools. Returns True only if the user typed y/yes."""
    return _handlers["confirm"](message)


@tool(
    "Call this when the task is completely done. Give a one-line summary.",
    parameters={
        "summary": {"type": "string", "description": "One-line summary of what was done"}
    },
    required=["summary"],
)
def finish(summary):
    return summary


@tool(
    "Ask the user a question and wait for their typed answer. Use when the request is "
    "unclear or there are several possible matches.",
    parameters={"question": {"type": "string", "description": "A short, clear question"}},
    required=["question"],
)
def ask_user(question):
    answer = _handlers["ask"](str(question))
    return answer or "(no answer)"


@tool(
    "Update the user identity and long-term memory. Use when the user asks to remember or forget personal facts.",
    parameters={
        "memory": {"type": "string", "description": "Complete markdown text for system memory"}
    },
    required=["memory"],
)
def update_system_memory(memory_text: str):
    try:
        memory.write_memory(memory_text)
        return "Successfully updated system memory."
    except Exception as e:
        return f"Error updating memory: {e}"


@tool(
    "Update your working scratchpad notes, checklist, and intermediate steps.",
    parameters={
        "notes": {"type": "string", "description": "Updated markdown scratchpad notes"}
    },
    required=["notes"],
)
def update_scratchpad(notes: str):
    try:
        memory.write_scratchpad(notes)
        return "Successfully saved scratchpad notes."
    except Exception as e:
        return f"Error saving scratchpad: {e}"
