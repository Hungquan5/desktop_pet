from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DesktopNotification:
    app_name: str
    summary: str
    body: str

    @property
    def context(self) -> str:
        parts = [f"App: {self.app_name}", f"Title: {self.summary}"]
        if self.body:
            parts.append(f"Message: {self.body}")
        return ". ".join(parts)


def decode_dbus_string(line: str) -> str | None:
    """Decode one dbus-monitor `string "..."` line."""
    stripped = line.strip()
    if not stripped.startswith("string "):
        return None
    literal = stripped[len("string ") :]
    try:
        value = ast.literal_eval(literal)
    except (SyntaxError, ValueError):
        return None
    return value if isinstance(value, str) else None


def notification_from_strings(values: list[str]) -> DesktopNotification | None:
    # Notify(app_name, replaces_id, app_icon, summary, body, ...)
    if len(values) < 4:
        return None
    app_name, _icon, summary, body = values[:4]
    if not app_name and not summary and not body:
        return None
    return DesktopNotification(app_name or "Unknown app", summary or "Notification", body)
