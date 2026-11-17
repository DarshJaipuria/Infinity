"""Infinity dynamic toolset functions."""

TOOL_SET_MAP = {}

# 1. coding_tools
try:
    from functions.coding_functions import coding_instructions, coding_tool_map
    TOOL_SET_MAP["coding_tools"] = {
        "tool_map": coding_tool_map,
        "instructions": coding_instructions,
    }
except Exception as e:
    TOOL_SET_MAP["coding_tools"] = {"tool_map": {}, "instructions": f"Unavailable: {e}"}

# 2. desktop_tools
try:
    from functions.desktop_functions import desktop_tool_map, desktop_tools_instructions
    TOOL_SET_MAP["desktop_tools"] = {
        "tool_map": desktop_tool_map,
        "instructions": desktop_tools_instructions,
    }
except Exception as e:
    TOOL_SET_MAP["desktop_tools"] = {"tool_map": {}, "instructions": f"Unavailable: {e}"}

# 3. file_modification_tools
try:
    from functions.file_modification_functions import (
        file_modification_instructions,
        file_modification_tool_map,
    )
    TOOL_SET_MAP["file_modification_tools"] = {
        "tool_map": file_modification_tool_map,
        "instructions": file_modification_instructions,
    }
except Exception as e:
    TOOL_SET_MAP["file_modification_tools"] = {"tool_map": {}, "instructions": f"Unavailable: {e}"}

# 4. read_file_tools
try:
    from functions.read_file_functions import (
        read_file_instructions,
        read_file_tool_map,
    )
    TOOL_SET_MAP["read_file_tools"] = {
        "tool_map": read_file_tool_map,
        "instructions": read_file_instructions,
    }
except Exception as e:
    TOOL_SET_MAP["read_file_tools"] = {"tool_map": {}, "instructions": f"Unavailable: {e}"}

# 5. web_search_tools
try:
    from functions.web_search_tools import web_search_instructions, web_search_tool_map
    TOOL_SET_MAP["web_search_tools"] = {
        "tool_map": web_search_tool_map,
        "instructions": web_search_instructions,
    }
except Exception as e:
    TOOL_SET_MAP["web_search_tools"] = {"tool_map": {}, "instructions": f"Unavailable: {e}"}

__all__ = ["TOOL_SET_MAP"]
