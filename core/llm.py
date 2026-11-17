from typing import Any, Generator, List, Optional
import ollama
import config


def _ctx():
    return getattr(config, "NUM_CTX", 12288)


class LLM:
    """Ollama inference client supporting chat, vision, JSON planning, and streaming."""

    def __init__(self, host: Optional[str] = None, model: Optional[str] = None):
        self.host = host or getattr(config, "OLLAMA_HOST", "http://localhost:11434")
        self.model = model or getattr(config, "MODEL", "qwen3.5:4b")
        self.client = ollama.Client(host=self.host)

    def chat(self, messages: List[dict], tools: Optional[List[dict]] = None, model: Optional[str] = None) -> Any:
        return self.client.chat(
            model=model or self.model,
            messages=messages,
            tools=tools or None,
            think=getattr(config, "THINK", False),
            options={"num_ctx": _ctx(), "num_predict": 4096},
        )

    def vision(self, prompt: str, image_path: str, model: Optional[str] = None) -> str:
        """Inspect an image using Ollama multimodal capabilities."""
        response = self.client.chat(
            model=model or self.model,
            messages=[{"role": "user", "content": prompt, "images": [image_path]}],
            think=getattr(config, "THINK", False),
            options={"temperature": 0.1, "num_ctx": _ctx(), "num_predict": 2048},
        )
        msg = getattr(response, "message", None)
        content = getattr(msg, "content", "") if msg else ""
        return (content or "").strip()

    def plan_json(
        self,
        system: str,
        user: str,
        schema: Any,
        temperature: float = 0.5,
        model: Optional[str] = None,
    ) -> str:
        """Request structured JSON adhering to given schema."""
        response = self.client.chat(
            model=model or self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            format=schema,
            think=getattr(config, "THINK", False),
            options={"temperature": temperature, "num_ctx": _ctx(), "num_predict": 3500},
        )
        msg = getattr(response, "message", None)
        return getattr(msg, "content", "") or ""

    def stream_text(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
        model: Optional[str] = None,
        think: bool = False,
        max_tokens: int = 7000,
    ) -> Generator[str, None, None]:
        """Stream response tokens sequentially from Ollama."""
        stream = self.client.chat(
            model=model or self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            think=think,
            stream=True,
            options={"temperature": temperature, "num_ctx": _ctx(), "num_predict": max_tokens},
        )
        for chunk in stream:
            msg = getattr(chunk, "message", None)
            piece = getattr(msg, "content", "") if msg else ""
            if piece:
                yield piece