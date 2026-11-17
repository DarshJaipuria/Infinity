from datetime import datetime
from . import tool


@tool("Get the current date and time.")
def get_time():
    return datetime.now().strftime("%A, %d %B %Y, %I:%M %p")


@tool(
    "Add two numbers together.",
    parameters={
        "a": {"type": "number", "description": "First number"},
        "b": {"type": "number", "description": "Second number"},
    },
    required=["a", "b"],
)
def add_numbers(a, b):
    return a + b