"""Known-good example programs. When a request matches, the model gets one as a quality bar."""
import os
import re

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "refs")

REFERENCES = [
    (re.compile(r"\bsnake\b", re.I), "snake.py"),
    (re.compile(r"tic[\s\-_]?tac[\s\-_]?toe|noughts", re.I), "tictactoe.py"),
]


def pick(request):
    """The source of the reference program that matches the request, or None."""
    for pattern, filename in REFERENCES:
        if pattern.search(request):
            try:
                with open(os.path.join(_DIR, filename), encoding="utf-8") as f:
                    return f.read()
            except OSError:
                return None
    return None
