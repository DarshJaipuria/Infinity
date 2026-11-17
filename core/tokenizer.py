import json
from typing import Any, List, Optional

try:
    import tiktoken
except ImportError:
    tiktoken = None


def count_tokens(
    messages: List[dict],
    model: Optional[str] = None,
    tools: Optional[Any] = None,
    **kwargs
) -> int:
    """Calculate token count for chat messages and schemas.
    Uses tiktoken when available, falling back to a 3-character/byte ratio.
    Multimodal image parts add an estimated 1024 tokens.
    """
    encoding = None
    if tiktoken is not None and model:
        try:
            encoding = tiktoken.encoding_for_model(model)
        except (KeyError, Exception):
            try:
                encoding = tiktoken.get_encoding("cl100k_base")
            except Exception:
                encoding = None

    def _text_count(text: str) -> int:
        if not text:
            return 0
        if encoding is not None:
            try:
                return len(encoding.encode(text, disallowed_special=()))
            except Exception:
                pass
        return (len(text.encode("utf-8", errors="ignore")) + 2) // 3

    token_count = 3  # priming tokens
    for msg in messages:
        token_count += 4  # message envelope overhead
        token_count += _text_count(str(msg.get("role", "")))

        content = msg.get("content", "")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    ptype = part.get("type", "")
                    if ptype in ("image", "image_url") or "image_url" in part:
                        token_count += 1024
                        for k, v in part.items():
                            if k not in ("image", "image_url"):
                                token_count += _text_count(
                                    json.dumps(v, ensure_ascii=False, separators=(",", ":"))
                                )
                    else:
                        token_count += _text_count(
                            json.dumps(part, ensure_ascii=False, separators=(",", ":"))
                        )
                elif isinstance(part, str):
                    token_count += _text_count(part)
        elif content is not None:
            token_count += _text_count(
                content if isinstance(content, str) else json.dumps(
                    content, ensure_ascii=False, separators=(",", ":")
                )
            )

        extra = {k: v for k, v in msg.items() if k not in ("role", "content")}
        if extra:
            token_count += _text_count(
                json.dumps(extra, ensure_ascii=False, separators=(",", ":"))
            )

    if tools:
        token_count += 8 + _text_count(
            json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
        )

    return token_count
