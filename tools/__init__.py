STATE = {}   # shared scratchpad that sub-tools write to during one main-tool run
TOOLS = {}
ACTIVE_TOOLSET = None

import json
from typing import Any, Dict, List, Optional


def tool(description, parameters=None, required=None):
    """Decorator that registers a function as a sub-tool."""
    def wrapper(func):
        TOOLS[func.__name__] = {
            "func": func,
            "schema": {
                "type": "function",
                "function": {
                    "name": func.__name__,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": parameters or {},
                        "required": required or [],
                    },
                },
            },
        }
        return func
    return wrapper


def get_schemas(names=None):
    """Schemas for the given tool names (or all tools if names is None)."""
    if names is None:
        return [t["schema"] for t in TOOLS.values()]
    return [TOOLS[n]["schema"] for n in names if n in TOOLS]


def get_all_schemas():
    return [t["schema"] for t in TOOLS.values()]


def run_tool(name, arguments):
    try:
        from core.logger import log
        log(f"CALL   {name} {arguments}")
    except Exception:
        log = None
    arguments = arguments or {}

    # 1. Check native registered tools
    if name in TOOLS:
        try:
            res = TOOLS[name]["func"](**arguments)
            result = str(res)
        except Exception as e:
            result = f"Error running {name}: {e}"
        if log:
            log(f"RESULT {name} -> {result[:200]}")
        return result

    # 2. Check dynamic Infinity functions
    try:
        from functions import TOOL_SET_MAP
        for ts_name, ts_info in TOOL_SET_MAP.items():
            tool_map = ts_info.get("tool_map", {})
            if name in tool_map:
                res = tool_map[name](**arguments)
                result = str(res)
                if log:
                    log(f"RESULT {name} -> {result[:200]}")
                return result
    except Exception as e:
        if log:
            log(f"Error searching dynamic tools: {e}")

    result = f"Error: unknown tool '{name}'"
    if log:
        log(f"RESULT {name} -> {result}")
    return result


from . import basic, control, code_tools, hands, eyes, files, gmail, web_tools  # noqa: E402,F401
