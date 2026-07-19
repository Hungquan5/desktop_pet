from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SessionLogger:
    def __init__(self, directory: Path = Path("logs"), enabled: bool = True) -> None:
        self.enabled = enabled
        self.path: Path | None = None
        if enabled:
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            self.path = directory / f"session-{stamp}.jsonl"

    def write(self, event_type: str, **data: Any) -> None:
        if not self.enabled or self.path is None:
            return
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            **data,
        }
        with self.path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

