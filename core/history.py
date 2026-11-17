import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

import config
from core.tokenizer import count_tokens

DEFAULT_MAX_MESSAGES = 10


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class ChatHistoryManager:
    """Manages local JSON chat history with sliding-window truncation,
    multimodal optimization, reasoning cleanup, and token statistics.
    """

    def __init__(self, filepath=None, max_messages=None, session_id=None):
        default_path = getattr(
            config,
            "CHAT_HISTORY_FILE",
            os.path.join(config.BASE_DIR, "data", "history.json"),
        )
        self.filepath = filepath or default_path
        configured_max = getattr(config, "MAX_HISTORY_MESSAGES", DEFAULT_MAX_MESSAGES)
        self.max_messages = (
            max_messages if max_messages is not None else configured_max
        )
        if self.max_messages < 0:
            self.max_messages = 0

        self.session_id = session_id or str(uuid.uuid4())
        self.messages: List[dict] = self.load()
        self.tokens: int = 0
        self.user_turn: bool = True
        self.instructions: Optional[str] = None
        self.update_tokens()

    def _truncate(self, messages: list[dict]) -> list[dict]:
        if self.max_messages == 0:
            return []
        return list(messages[-self.max_messages:])

    def _sanitize_messages(self, raw_messages) -> list[dict]:
        if not isinstance(raw_messages, list):
            return []
        cleaned = []
        for item in raw_messages:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role not in ("user", "assistant", "system", "tool"):
                continue
            cleaned_item = dict(item)
            if content is None and not item.get("tool_calls"):
                continue
            cleaned.append(cleaned_item)
        return self._truncate(cleaned)

    def optimize_history(self, keep_images: Optional[int] = None, keep_reasoning: int = 5) -> None:
        """Prune older screenshots and reasoning blobs to prevent token overflow."""
        n_imgs = keep_images if keep_images is not None else getattr(config, "KEEP_IMAGES", 1)
        h = self.messages

        # 1. Prune excessive images in tool and user messages
        img_indices = []
        for i, msg in enumerate(h):
            if isinstance(msg.get("content"), list):
                for part in msg["content"]:
                    if isinstance(part, dict) and (part.get("image_url") or part.get("type") == "image"):
                        img_indices.append(i)
                        break

        if len(img_indices) > n_imgs:
            excess = len(img_indices) - n_imgs
            for idx in img_indices[:excess]:
                content = h[idx].get("content")
                if isinstance(content, list):
                    for j, part in enumerate(content):
                        if isinstance(part, dict) and (part.get("image_url") or part.get("type") == "image"):
                            content[j] = {
                                "type": "text",
                                "text": "[Attached Image/Screenshot removed to save tokens]",
                            }

        # 2. Prune old reasoning content
        reasoning_msgs = [
            msg for msg in h
            if msg.get("role") == "assistant" and (msg.get("reasoning_content") or msg.get("reasoning"))
        ]
        if len(reasoning_msgs) > keep_reasoning:
            excess = len(reasoning_msgs) - keep_reasoning
            for msg in reasoning_msgs[:excess]:
                msg.pop("reasoning_content", None)
                msg.pop("reasoning", None)

        self.update_tokens()

    def update_tokens(self, model: Optional[str] = None, tools: Optional[Any] = None) -> int:
        """Recalculate token count of active messages."""
        m = model or getattr(config, "MODEL", "qwen3.5:4b")
        self.tokens = count_tokens(self.messages, model=m, tools=tools)
        return self.tokens

    def return_tokens(self) -> str:
        self.update_tokens()
        ctx = getattr(config, "CTX_TOKEN", 12288)
        pct = (self.tokens / ctx * 100) if ctx else 0
        return f"Token count: {self.tokens}/{ctx} ({pct:.1f}%)"

    def _write_file(self, messages: list[dict]) -> None:
        parent = os.path.dirname(os.path.abspath(self.filepath))
        if parent:
            os.makedirs(parent, exist_ok=True)

        payload = {
            "session_id": self.session_id,
            "updated_at": _now_iso(),
            "messages": self._truncate(messages),
        }

        fd, tmp_path = tempfile.mkstemp(
            prefix=".chat_history_", suffix=".tmp", dir=parent or "."
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, self.filepath)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

    def load(self) -> list[dict]:
        if not os.path.exists(self.filepath):
            self.messages = []
            self._write_file(self.messages)
            return []

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                raw_text = f.read().strip()
            if not raw_text:
                raise ValueError("Empty chat history file")
            data = json.loads(raw_text)
            if isinstance(data, list):
                # Infinity raw list format
                self.messages = self._sanitize_messages(data)
                return list(self.messages)
            if not isinstance(data, dict):
                raise ValueError("Chat history root must be a JSON object or array")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self.messages = []
            self._write_file(self.messages)
            return []

        loaded_session = data.get("session_id")
        if isinstance(loaded_session, str) and loaded_session.strip():
            self.session_id = loaded_session.strip()

        raw_messages = data.get("messages", [])
        sanitized = self._sanitize_messages(raw_messages)
        self.messages = sanitized

        if (
            not isinstance(raw_messages, list)
            or len(sanitized) != len(raw_messages)
            or "session_id" not in data
            or "updated_at" not in data
        ):
            self._write_file(self.messages)

        return list(self.messages)

    def save(self, messages: list[dict]) -> list[dict]:
        self.messages = self._sanitize_messages(messages)
        self._write_file(self.messages)
        self.update_tokens()
        return list(self.messages)

    def append_turn(self, user_content: Any, assistant_content: Any) -> list[dict]:
        updated = list(self.messages)
        updated.append({"role": "user", "content": user_content})
        updated.append({"role": "assistant", "content": assistant_content})
        return self.save(updated)

    def clear(self, new_session: bool = True) -> None:
        if new_session:
            self.session_id = str(uuid.uuid4())
        self.messages = []
        self._write_file(self.messages)
        self.tokens = 0

    def get_messages(self) -> list[dict]:
        return list(self._truncate(self.messages))


# Alias for compatibility with Infinity classes
History = ChatHistoryManager
