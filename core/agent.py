import inspect
import json
import re
import config
from core import memory
from core.history import ChatHistoryManager
from core.llm import LLM
from core.skill import run_skill
from core.tokenizer import count_tokens
import skills
import tools

_ACTION_CLAIM_RE = re.compile(
    r"(✔|copied\s+file|renamed\s*:|created\s+file|created\s+folder|deleted\s+|"
    r"copy\s+and\s+rename\s+completed|screenshot\s+saved|updated\s+content)",
    re.IGNORECASE,
)

_ACTION_REQUEST_RE = re.compile(
    r"\b(copy|rename|move|delete|remove|create|write|patch|find|solve|screenshot|screen\s*shot|"
    r"mouse\s+cursor|mouse\s+position|cursor\s+position|pointer\s+position|"
    r"coordinates\s+of\s+my\s+mouse)\b",
    re.IGNORECASE,
)


def _clean_content(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<think>.*?</think>", "", str(text), flags=re.S).strip()
    return cleaned


def _filter_args(name: str, args: dict) -> dict:
    if not isinstance(args, dict):
        return {}
    entry = tools.TOOLS.get(name)
    if not entry:
        return args
    func = entry.get("func")
    if not func:
        return args
    try:
        sig = inspect.signature(func)
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            return args
        allowed = set(sig.parameters.keys())
        mapped = dict(args)
        if "dest_folder" in allowed and "dest_folder" not in mapped:
            for alias in ("destination", "dest", "target", "to", "new_path"):
                if alias in mapped:
                    mapped["dest_folder"] = mapped.pop(alias)
                    break
        if "source" in allowed and "source" not in mapped:
            for alias in ("src", "path", "file", "from_path"):
                if alias in mapped:
                    mapped["source"] = mapped.pop(alias)
                    break
        if "path" in allowed and "path" not in mapped:
            for alias in ("source", "src", "file", "old_name", "old_path", "folder", "directory"):
                if alias in mapped:
                    mapped["path"] = mapped.pop(alias)
                    break
        if "new_name" in allowed and "new_name" not in mapped:
            for alias in ("target", "dest", "destination", "to", "new_path", "name"):
                if alias in mapped:
                    mapped["new_name"] = mapped.pop(alias)
                    break
        return {k: v for k, v in mapped.items() if k in allowed}
    except Exception:
        return args


class Agent:
    def __init__(self, on_event=None, history_path=None, max_history=None):
        self.llm = LLM()
        self.on_event = on_event or (lambda kind, data: None)
        self.history = ChatHistoryManager(
            filepath=history_path,
            max_messages=max_history,
        )
        self.active_toolset = None
        self._load_context()

    def _get_system_prompt(self) -> str:
        base_prompt = getattr(config, "SYSTEM_PROMPT", "You are Infinity, an AI assistant.")
        mem = memory.read_memory()
        scratch = memory.read_scratchpad()
        dt = memory.get_datetime_str()

        additions = []
        if mem:
            additions.append(f"## System Memory (User facts):\n{mem}")
        if scratch:
            additions.append(f"## Current Working Scratchpad:\n{scratch}")
        additions.append(f"- Date/Time: {dt}")

        if additions:
            return f"{base_prompt}\n\n" + "\n\n".join(additions)
        return base_prompt

    def _load_context(self):
        self.messages = [
            {"role": "system", "content": self._get_system_prompt()},
            *self.history.get_messages(),
        ]

    def _context_messages(self):
        """Return system prompt + at most the most recent max_messages entries."""
        limit = self.history.max_messages
        tail = self.messages[1:][-limit:] if limit > 0 else []
        return [{"role": "system", "content": self._get_system_prompt()}, *tail]

    def _finalize_turn(self, user_text, answer):
        answer = _clean_content(answer) or "(No response generated)"
        self.history.optimize_history()
        truncated = self.history.append_turn(user_text, answer)
        self.messages = [
            {"role": "system", "content": self._get_system_prompt()},
            *truncated,
        ]
        return answer

    def reset(self):
        self.history.clear(new_session=True)
        self.messages = [{"role": "system", "content": self._get_system_prompt()}]

    def get_token_stats(self) -> str:
        count = count_tokens(self.messages, model=config.MODEL)
        ctx = getattr(config, "CTX_TOKEN", 12288)
        pct = (count / ctx * 100) if ctx else 0
        return f"Tokens: {count}/{ctx} ({pct:.1f}%)"

    def run(self, user_text):
        self.messages.append({"role": "user", "content": user_text})

        # Assemble top-level tool schemas: skills + direct tools (including PDF, DOCX, CSV, JSON, Image readers)
        schemas = list(skills.get_schemas())
        control_schemas = tools.get_schemas([
            "update_system_memory",
            "update_scratchpad",
            "ask_user",
            "create_file",
            "write_file",
            "read_file",
            "read_pdf",
            "read_docx",
            "read_image",
            "read_csv",
            "read_json",
            "patch_file",
            "create_folder",
            "list_folder",
            "find_item",
            "path_exists",
            "copy_item",
            "move_item",
            "rename_item",
            "delete_item",
            "get_mouse_position",
            "get_screen_size",
            "take_screenshot",
            "get_active_window",
            "describe_screen",
            "read_screen_text",
            "find_text_on_screen",
            "click_text",
            "verify_screen",
            "mouse_move",
            "click",
            "double_click",
            "right_click",
            "scroll",
            "type_text",
            "press_key",
            "hotkey",
            "wait",
            "get_weather",
            "web_search",
            "read_webpage",
            "wiki_summary",
            "get_time",
        ])
        schemas.extend(control_schemas)

        tool_outputs = []
        nudged_no_tool = False

        for step in range(1, config.MAX_STEPS + 1):
            response = self.llm.chat(
                self._context_messages(),
                tools=schemas,
            )
            msg = response.message
            self.messages.append(msg)

            # No tool requested -> check for hallucinated actions or empty output
            if not msg.tool_calls:
                content = _clean_content(getattr(msg, "content", "") or "")

                # Guard against hallucinated file/system actions when zero tools were called
                if not tool_outputs and not nudged_no_tool and (
                    _ACTION_CLAIM_RE.search(content) or _ACTION_REQUEST_RE.search(user_text)
                ):
                    nudged_no_tool = True
                    self.messages.pop()
                    self.messages.append({
                        "role": "system",
                        "content": (
                            "You did NOT call any tool yet. Do NOT claim an action was completed "
                            "or guess file contents without reading the file first. Call the appropriate tool "
                            "(e.g. find_item, list_folder, read_file, read_pdf, read_docx, copy_item, rename_item, "
                            "take_screenshot, get_mouse_position) now."
                        ),
                    })
                    continue

                if not content and tool_outputs:
                    try:
                        synth = self.llm.chat(
                            self._context_messages() + [{
                                "role": "user",
                                "content": (
                                    f"Based on the tool results above, fulfill the user's request "
                                    f"completely (if solving an assignment, display the full step-by-step "
                                    f"answer for every question): {user_text}"
                                ),
                            }],
                            tools=None,
                        )
                        content = _clean_content(getattr(synth.message, "content", "") or "")
                    except Exception:
                        content = ""
                    if not content:
                        content = "\n".join(str(o) for o in tool_outputs if str(o).strip())

                if not content:
                    try:
                        retry = self.llm.chat(self._context_messages(), tools=None)
                        content = _clean_content(getattr(retry.message, "content", "") or "")
                    except Exception:
                        content = ""

                return self._finalize_turn(user_text, content or "Task completed.")

            direct_return_candidate = None
            for call in msg.tool_calls:
                name = call.function.name
                args = call.function.arguments or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}

                # 1. Check if it's a registered skill
                skill = skills.SKILLS.get(name)
                if skill is not None:
                    request = args.get("request", user_text)
                    if len(msg.tool_calls) == 1 and name in ("web_research", "file_manager"):
                        request = user_text
                    self.on_event("skill_start", f"▶ {name}: {request}")
                    result = run_skill(skill, request, self.llm, self.on_event)
                    self.on_event("skill_end", f"■ {name} finished")
                    self.messages.append(
                        {"role": "tool", "tool_name": name, "content": result}
                    )
                    if result and str(result).strip():
                        tool_outputs.append(str(result).strip())
                    if skill.direct_output and len(msg.tool_calls) == 1:
                        if name in ("write_code", "gmail_compose"):
                            direct_return_candidate = result
                        elif name == "web_research" and tools.STATE.get("research"):
                            direct_return_candidate = result
                    continue

                # 2. Check if it's a sub-tool or control tool
                filtered_args = _filter_args(name, args)
                self.on_event("tool_call", f"⚙ {name}({filtered_args})")
                result = tools.run_tool(name, filtered_args)
                self.on_event("tool_result", f"→ {result[:120]}")
                self.messages.append(
                    {"role": "tool", "tool_name": name, "content": result}
                )
                if result and str(result).strip():
                    tool_outputs.append(str(result).strip())

            if direct_return_candidate and str(direct_return_candidate).strip():
                return self._finalize_turn(user_text, direct_return_candidate)

        if tool_outputs:
            try:
                final_resp = self.llm.chat(
                    self._context_messages() + [{
                        "role": "user",
                        "content": (
                            f"Using all the information and file contents retrieved above, complete every part "
                            f"of the user's request in full detail: {user_text}"
                        ),
                    }],
                    tools=None,
                )
                final_text = _clean_content(getattr(final_resp.message, "content", "") or "")
                if final_text:
                    return self._finalize_turn(user_text, final_text)
            except Exception:
                pass
            return self._finalize_turn(user_text, "\n".join(tool_outputs))

        return self._finalize_turn(
            user_text, "Stopped: reached the maximum number of steps."
        )