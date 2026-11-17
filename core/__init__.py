"""Infinity Core Modules."""
from core.history import ChatHistoryManager, History
from core.llm import LLM
from core.memory import read_memory, read_scratchpad, write_memory, write_scratchpad
from core.tokenizer import count_tokens

def __getattr__(name):
    if name == "Agent":
        from core.agent import Agent
        return Agent
    raise AttributeError(f"module 'core' has no attribute '{name}'")

__all__ = [
    "Agent",
    "ChatHistoryManager",
    "History",
    "LLM",
    "read_memory",
    "write_memory",
    "read_scratchpad",
    "write_scratchpad",
    "count_tokens",
]
