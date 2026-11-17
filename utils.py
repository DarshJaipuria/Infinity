import base64
from datetime import datetime
import json
import os
from typing import Any, List, Literal, Optional

import config
from core import logger, memory, tokenizer

# System Prompts & Templates
SYSTEM_PROMPT = """# Role and Core Objective
You are Infinity, a smart AI assistant with access to multiple tool sets. Respond to the user's request directly when no tool is required. Select the narrowest tool set that matches the user's intent; do not choose a tool set merely because it contains a similarly named function.

# PRIORITY Rules
- Use a tool set only when it is required or the user asks explicitly. Follow the instructions of each tool set strictly when using that tool set.
- Always follow given formats.
- If a tool fails, write the error details into your scratchpad, adjust your approach, and try a different tool or method immediately.
- Never repeat the exact same tool call parameters twice in a row if it fails.
- Only call `clear_context` tool when context limit warning is triggered. Do not use this tool in any other case.

# Memory and Notes Management
## System Memory
- Only call `update_memory` when the user explicitly says to remember/forget personal facts. If called, output your complete, updated markdown tree (# System Memory, ## User Core Identity, ## Facts and Information).
- System memory is for storing user related information and facts only.

## Scratchpad Notes
- State your immediate next step in ONE short sentence.
- If plans change or a tool fails, IMMEDIATELY call `update_scratchpad` to update your checklist.

# Instructions for Current Tool Set
{instructions}

{system_memory}

# Your Scratchpad Notes
{scratchpad_notes}

# System Info
- Current Date and Time: {dt}
- Current tool set: {tool_set}"""

WORKFLOW_PROMPT = """# Role and Core Objective
You are an expert Workflow & Skill Design Architect. Your primary objective is to analyze user requests, task execution logs, or multi-step procedures, and convert them into complete, fully self-contained, and deterministic workflow manuals (`SKILL.md`) for future reuse by autonomous AI agents.

# Priority Rules
1. **Zero Ambiguity:** Do not include vague instructions. Specify exact commands, file structures, schemas, and script parameters required at every step.
2. **Self-Containment:** The workflow must contain all necessary documentation, code templates, prerequisites, edge-case handlers, and error recovery steps to complete the task autonomously without human intervention.
3. **Deterministic Structure:** Organize workflows sequentially with clear logical branching, verification loops, and success criteria.
4. **Tool & Capability Scoping:** Explicitly list required permissions and external dependencies.
5. **Single-Effective-Method:** Should contain only one reliable, tested method.
6. Always read the old workflow using `read_workflow` tool first then rewrite it.

# Output Format
Output the finalized workflow as valid Markdown text.
"""

CLEAR_CONTEXT_PROMPT = """- Use the following format explicitly for message:
```markdown
# Context
## Ongoing Task (if any)
- Current Task: Task provided by user and not yet completed by agent. If no incomplete task then only None.
- Task Details (if Task): Mention any necessary details required for the task.
- Additional Context (if task): More background context or None.

## Recent Chat memory
1. Summarize the current chat both user request and agent's response, keep it short and crisp.
2. The list must be in descending order, newest first.
3. Keep maximum old chat memory possible while adding new memory without exceeding the limits.
```
"""

# Global schemas
GLOBAL_TOOLS_PATH = os.path.join(config.BASE_DIR, "global_tools.json")
try:
    with open(GLOBAL_TOOLS_PATH, "r", encoding="utf-8") as _f:
        global_tools = json.load(_f)
except Exception:
    global_tools = []


def load_schema(name: str) -> List[dict]:
    if not name.endswith(".json"):
        name += ".json"
    path = os.path.join(config.BASE_DIR, "tools_schema", name)
    try:
        with open(path, "r", encoding="utf-8") as file:
            schema = json.load(file)
    except FileNotFoundError:
        schema = []
    return schema + global_tools


def load_config(path: Optional[str] = None) -> dict:
    target = path or config.CONFIG_JSON_PATH
    try:
        with open(target, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_base64_url(path: str) -> str:
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def log(
    line: str,
    path: Optional[str] = None,
    level: Literal["DEBUG", "INFO", "WARN", "ERROR", "FATAL"] = "INFO",
) -> None:
    logger.log(line, path=path, level=level)


def save_history(hist: list, path: Optional[str] = None) -> None:
    target = path or config.CHAT_HISTORY_FILE
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(hist, f, indent=4, ensure_ascii=False)


def load_history(path: Optional[str] = None) -> list:
    target = path or config.CHAT_HISTORY_FILE
    try:
        with open(target, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("messages", [])
    except Exception:
        pass
    return [{"role": "system", "content": SYSTEM_PROMPT}]


def read_memory() -> str:
    return memory.read_memory()


def write_memory(mem: str) -> None:
    memory.write_memory(mem)


def read_scratchpad_notes() -> str:
    return memory.read_scratchpad()


def write_scratchpad_notes(notes: str) -> None:
    memory.write_scratchpad(notes)


def get_datetime() -> str:
    return memory.get_datetime_str()


def count_tokens(messages: list, model: Optional[str] = None, url: Optional[str] = None, api_key: Optional[str] = None, tools: Optional[Any] = None) -> int:
    return tokenizer.count_tokens(messages, model=model, tools=tools)
