import json
import os
import time
from typing import Literal, Optional
import config

LOG_PATH = getattr(config, "LOGS_FILE", os.path.join(config.BASE_DIR, "data", "logs.log"))


def log(
    message: str,
    path: Optional[str] = None,
    level: Literal["DEBUG", "INFO", "WARN", "ERROR", "FATAL"] = "INFO",
) -> None:
    """Log formatted entry to disk."""
    target_path = path or LOG_PATH
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")

    entry = {
        "timestamp": stamp,
        "level": str(level),
        "details": str(message),
    }

    try:
        with open(target_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
