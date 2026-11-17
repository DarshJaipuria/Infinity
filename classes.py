import os
import threading
import time
from typing import Any, Dict, Generator, List, Optional

import ollama
from rich.console import Console
from rich.live import Live
from rich.text import Text

import config as app_config
import utils

console = Console()


class _OllamaCompletions:
    """Provides OpenAI-style completions API over native Ollama client."""

    def __init__(self, ollama_client: ollama.Client):
        self._client = ollama_client

    def create(
        self,
        model: Optional[str] = None,
        messages: Optional[List[dict]] = None,
        stream: bool = False,
        tools: Optional[List[dict]] = None,
        options: Optional[dict] = None,
        **kwargs,
    ) -> Any:
        target_model = model or getattr(app_config, "MODEL", "qwen3.5:4b")
        opts = options or {"num_ctx": getattr(app_config, "NUM_CTX", 12288)}

        # Format tools if provided
        ollama_tools = []
        if tools:
            for t in tools:
                if isinstance(t, dict) and t.get("type") == "function" and "function" in t:
                    ollama_tools.append(t["function"])
                else:
                    ollama_tools.append(t)

        try:
            res = self._client.chat(
                model=target_model,
                messages=messages or [],
                stream=stream,
                tools=ollama_tools if ollama_tools else None,
                options=opts,
            )
        except Exception as e:
            utils.log(f"Ollama chat error: {e}", level="ERROR")
            raise e

        if stream:
            return self._stream_adapter(res)
        return self._response_adapter(res)

    def _stream_adapter(self, stream) -> Generator[Any, None, None]:
        class _Delta:
            def __init__(self, content="", tool_calls=None, reasoning=None):
                self.content = content
                self.tool_calls = tool_calls
                self.reasoning = reasoning
                self.reasoning_content = reasoning

        class _Choice:
            def __init__(self, delta):
                self.delta = delta

        class _Chunk:
            def __init__(self, choice):
                self.choices = [choice]

        for chunk in stream:
            msg = getattr(chunk, "message", None)
            content = getattr(msg, "content", "") if msg else ""
            tool_calls = getattr(msg, "tool_calls", None) if msg else None
            reasoning = getattr(msg, "thinking", None) if msg else None
            yield _Chunk(_Choice(_Delta(content=content, tool_calls=tool_calls, reasoning=reasoning)))

    def _response_adapter(self, res) -> Any:
        class _Message:
            def __init__(self, content="", tool_calls=None):
                self.content = content
                self.tool_calls = tool_calls

        class _Choice:
            def __init__(self, message):
                self.message = message

        class _Response:
            def __init__(self, choice):
                self.choices = [choice]

        msg = getattr(res, "message", None)
        content = getattr(msg, "content", "") if msg else ""
        tool_calls = getattr(msg, "tool_calls", None) if msg else None
        return _Response(_Choice(_Message(content=content, tool_calls=tool_calls)))


class _ChatHandler:
    """Callable chat handler that also exposes .completions.create()."""

    def __init__(self, ollama_client: ollama.Client):
        self._client = ollama_client
        self.completions = _OllamaCompletions(ollama_client)

    def __call__(self, *args, **kwargs) -> Any:
        return self._client.chat(*args, **kwargs)


class OllamaClient(ollama.Client):
    """Native Ollama client wrapper with OpenAI-adapter compatibility."""

    def __init__(self, host: str = "http://localhost:11434"):
        super().__init__(host=host)
        self.chat = _ChatHandler(self)  # type: ignore[assignment]


class ToolSet:
    """Maintains active toolset and function schemas."""

    def __init__(self):
        self.tool_set: Optional[str] = None
        self.tools: List[dict] = list(getattr(utils, "global_tools", []))
        self.tool_map: Optional[Dict[str, Any]] = None


class Config:
    """Loads configuration and instantiates Ollama client."""

    def __init__(self):
        self.host: str = "http://localhost:11434"
        self.url: str = self.host
        self.model: str = "qwen3.5:4b"
        self.client: OllamaClient = OllamaClient(host=self.host)
        self.ctx_token: int = 12288
        self.buffer_token: int = 2048
        self.res_x: int = 1920
        self.res_y: int = 1080
        self.mon: int = 1
        self.image_n: int = 1
        self.n_retry: int = 3
        self.max_chrs: int = 10000
        self.update_config()

    def update_config(self) -> None:
        app_config.update_from_json()
        cfg = utils.load_config()

        self.host = cfg.get("ollama_host", getattr(app_config, "OLLAMA_HOST", "http://localhost:11434"))
        self.url = self.host
        self.model = cfg.get("model_id", getattr(app_config, "MODEL", "qwen3.5:4b"))

        try:
            self.client = OllamaClient(host=self.host)
        except Exception as e:
            utils.log(f"Failed to create OllamaClient at {self.host}: {e}", level="WARN")

        self.ctx_token = int(cfg.get("context_length", getattr(app_config, "NUM_CTX", 12288)))
        self.buffer_token = int(cfg.get("buffer_token", getattr(app_config, "BUFFER_TOKEN", 2048)))
        res = cfg.get("screen_resolution", {"x": 1920, "y": 1080})
        self.res_x = int(res.get("x", 1920))
        self.res_y = int(res.get("y", 1080))
        self.mon = int(cfg.get("primary_monitor", 1))
        self.image_n = int(cfg.get("keep_images", 1))
        self.n_retry = int(cfg.get("n_retry", 3))
        self.max_chrs = int(cfg.get("max_characters", 10000))


# Pre-instantiate singletons so History has full access to defined variables
config = Config()
tools = ToolSet()


class History:
    """Manages chat turn persistence, tokens, and multimodal optimization."""

    def __init__(self):
        self.user_turn: bool = True
        self.instructions: Optional[str] = None
        self.history: List[dict] = utils.load_history()
        self.tokens: int = 0
        self.timer: bool = False
        self.optimize_history()
        utils.save_history(self.history)
        self.update()

    @property
    def messages(self) -> List[dict]:
        return self.history

    @messages.setter
    def messages(self, val: List[dict]) -> None:
        self.history = val

    def update_sys_prompt(self) -> None:
        system_content = utils.SYSTEM_PROMPT.format(
            tool_set=tools.tool_set or "global_tools",
            instructions=self.instructions or "",
            system_memory=utils.read_memory(),
            dt=f"Current Date and Time: {utils.get_datetime()}",
            scratchpad_notes=utils.read_scratchpad_notes(),
        )
        if self.history and self.history[0].get("role") == "system":
            self.history[0]["content"] = system_content
        else:
            self.history.insert(0, {"role": "system", "content": system_content})

    def update(self) -> None:
        self.tokens = utils.count_tokens(
            messages=self.history,
            model=config.model,
            tools=tools.tools,
        )

    def print_tokens(self, c: Console) -> None:
        self.update()
        ctx = config.ctx_token
        pct = (self.tokens / ctx * 100) if ctx else 0
        c.print(f"Token count: {self.tokens}/{ctx}; {pct:.2f}%", style="yellow")

    def return_tokens(self) -> str:
        self.update()
        ctx = config.ctx_token
        pct = (self.tokens / ctx * 100) if ctx else 0
        return f"Token count: {self.tokens}/{ctx}; {pct:.2f}%"

    def optimize_history(self) -> None:
        # 1. Prune screenshots beyond image_n
        n = config.image_n
        img_index_list = []
        for i, item in enumerate(self.history):
            if item.get("role") == "tool" and isinstance(item.get("content"), list):
                for part in item["content"]:
                    if isinstance(part, dict) and part.get("image_url"):
                        img_index_list.append(i)
                        break

        if len(img_index_list) > n:
            excess = len(img_index_list) - n
            for idx in img_index_list[:excess]:
                content = self.history[idx].get("content")
                if isinstance(content, list):
                    for j, part in enumerate(content):
                        if isinstance(part, dict) and part.get("image_url"):
                            content[j] = {
                                "type": "text",
                                "text": "Attached Image/Screenshot has been removed to save token space.",
                            }

        # 2. Prune reasoning content beyond last 5 turns
        c = sum(
            1 for msg in self.history
            if msg.get("role") == "assistant" and (msg.get("reasoning_content") or msg.get("reasoning"))
        )
        idx = 0
        while c > 5 and idx < len(self.history):
            msg = self.history[idx]
            if msg.get("role") == "assistant" and (msg.get("reasoning_content") or msg.get("reasoning")):
                msg.pop("reasoning_content", None)
                msg.pop("reasoning", None)
                c -= 1
            idx += 1

    def start_timer(self, live: Live, text: str, color: str = "cyan") -> None:
        def run_timer():
            start_t = time.time()
            while self.timer:
                elapsed = time.time() - start_t
                live.update(Text(f"{text}... {elapsed:.1f}s", style=color), refresh=True)
                time.sleep(0.05)

        self.timer = True
        threading.Thread(target=run_timer, daemon=True).start()

    def stop_timer(self, live: Live) -> None:
        self.timer = False
        time.sleep(0.05)
        live.update("", refresh=True)


history = History()
