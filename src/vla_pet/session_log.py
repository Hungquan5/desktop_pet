from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vla_pet.paths import AppPaths, ensure_private_directory

PRIVATE_KEYS = {
    "body",
    "chat",
    "content",
    "conversation",
    "message",
    "notification",
    "question",
    "screen_text",
    "text",
    "title",
    "window_title",
}


def redact_private_data(value: Any, *, key: str = "") -> Any:
    if key.lower() in PRIVATE_KEYS:
        length = len(value) if isinstance(value, (str, bytes, list, tuple, dict)) else 0
        return {"redacted": True, "length": length}
    if isinstance(value, dict):
        return {str(child_key): redact_private_data(child, key=str(child_key)) for child_key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_private_data(child) for child in value]
    return value


class SessionLogger:
    def __init__(self, directory: Path | None = None, enabled: bool = True) -> None:
        self.enabled = enabled
        self.path: Path | None = None
        if enabled:
            directory = directory or AppPaths.discover().log_directory
            ensure_private_directory(directory)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            self.path = directory / f"session-{stamp}-{os.getpid()}.jsonl"

    def write(self, event_type: str, **data: Any) -> None:
        if not self.enabled or self.path is None:
            return
        record = redact_private_data({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            **data,
        })
        descriptor = os.open(
            self.path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        with os.fdopen(descriptor, "a", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self.path.chmod(0o600)
