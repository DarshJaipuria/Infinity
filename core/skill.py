import re
import config
import tools
from core import safety

try:
    from core import desktop
except Exception:
    desktop = None

# After these tools, the active window title is appended to the result (free observation)
SCREEN_TOOLS = {
    "mouse_move", "click", "double_click", "right_click", "drag_path",
    "scroll", "type_text", "press_key", "hotkey", "click_text",
}

SKILL_RULES = """You are carrying out a task using the tools provided.
Work step by step and use ONLY the tools you are given.
Never claim an operation succeeded unless you actually called the tool and it returned success.
If the user request has multiple steps or multiple questions, complete ALL of them before calling finish.
Read each tool result carefully. If it says Error or Not found, fix the cause and retry with corrected arguments.
When the entire task is done, call finish with a complete response covering all parts of the request."""


def _clean(text):
    if not text:
        return ""
    return re.sub(r"<think>.*?</think>", "", str(text), flags=re.S).strip()


def run_skill(skill, request, llm, on_event):
    try:
        return _run_skill(skill, request, llm, on_event)
    finally:
        if skill.cleanup:
            try:
                skill.cleanup()
            except Exception:
                pass


def _run_skill(skill, request, llm, on_event):
    safety.clear_kill()
    tools.STATE.clear()
    tools.STATE["in_skill"] = True
    tools.STATE["raw_request"] = request
    messages = [
        {"role": "system", "content": SKILL_RULES + "\n\n" + skill.playbook},
        {"role": "user", "content": request},
    ]
    allowed = list(skill.tools) + ["finish"]
    schemas = tools.get_schemas(allowed)
    summary = None
    tool_results = []
    max_steps = skill.max_steps or config.MAX_SKILL_STEPS

    for step in range(1, max_steps + 1):
        response = llm.chat(messages, tools=schemas)
        msg = response.message
        messages.append(msg)

        if not msg.tool_calls:
            summary = _clean(msg.content or "")
            break

        for call in msg.tool_calls:
            name = call.function.name
            args = call.function.arguments
            if isinstance(args, str):
                try:
                    import json
                    args = json.loads(args)
                except Exception:
                    args = {}
            on_event("tool_call", f"[{skill.name} step {step}] {name}({str(args)[:200]})")

            if name not in allowed:
                result = f"Error: tool '{name}' is not available here."
            elif skill.name == "web_research" and name == "research_topic" and tools.STATE.get("research"):
                result = "Research already completed."
                summary = result
            else:
                result = tools.run_tool(name, args)
                if skill.name == "web_research" and name == "research_topic" and tools.STATE.get("research"):
                    summary = result

            # Free observation: which window is in front now?
            if desktop and name in SCREEN_TOOLS and not tools.STATE.get("abort"):
                result += f"\n[active window: {desktop.foreground_title() or 'unknown'}]"

            on_event("tool_result", f"[{skill.name} step {step}] -> {str(result)[:300]}")
            messages.append({"role": "tool", "tool_name": name, "content": result})
            if name != "finish" and result:
                tool_results.append(str(result))

            # User pressed Esc or focus was lost: stop everything
            if tools.STATE.get("abort"):
                return result

            if name == "finish":
                summary = _clean(result)

            if summary is not None and skill.name == "web_research":
                break

        if summary is not None:
            break

    if not summary:
        if tool_results:
            try:
                synth = llm.chat(
                    messages + [{
                        "role": "user",
                        "content": f"Complete the user's request in full based on the tool outputs above: {request}",
                    }],
                    tools=None,
                )
                summary = _clean(getattr(synth.message, "content", "") or "")
            except Exception:
                summary = ""
            if not summary:
                summary = "\n".join(tool_results)
        else:
            summary = "Stopped: reached the maximum number of steps."

    # If a file reader ran inside file_manager and summary is just a short status line, include the read content
    last_read = tools.STATE.get("last_read_content")
    if skill.name == "file_manager" and last_read and len(summary) < 250:
        summary = f"{summary}\n\nExtracted Document Content:\n{last_read}"

    if skill.finalize:
        return skill.finalize(summary)
    return summary