from datetime import datetime
import os
import config


def get_datetime_str() -> str:
    """Return formatted current date and time."""
    now = datetime.now()
    return now.strftime(r"%A, %d-%B-%Y, %I:%M %p")


def read_memory() -> str:
    """Read user facts and identity from memory.md."""
    path = getattr(config, "MEMORY_FILE", os.path.join(config.BASE_DIR, "data", "memory.md"))
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def write_memory(content: str) -> None:
    """Write or update user facts in memory.md."""
    path = getattr(config, "MEMORY_FILE", os.path.join(config.BASE_DIR, "data", "memory.md"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def read_scratchpad() -> str:
    """Read ephemeral agent working notes from agent_scratchpad.md."""
    path = getattr(config, "SCRATCHPAD_FILE", os.path.join(config.BASE_DIR, "data", "agent_scratchpad.md"))
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def write_scratchpad(notes: str) -> None:
    """Save updated working notes/checklist to agent_scratchpad.md."""
    path = getattr(config, "SCRATCHPAD_FILE", os.path.join(config.BASE_DIR, "data", "agent_scratchpad.md"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(notes)
