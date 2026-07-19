from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from vla_pet.permissions import Capability
from vla_pet.persistence import StateRepository
from vla_pet.tool_runtime import (
    ToolInvocation,
    ToolManifest,
    ToolRegistry,
    ToolRisk,
    approved_path_scope,
)

OBJECT_SCHEMA = {"type": "object", "properties": {}}


@dataclass(slots=True)
class CoreToolServices:
    repository: StateRepository
    clipboard_reader: Callable[[], str] | None = None
    application_opener: Callable[[str], bool] | None = None


def _schema(properties: dict[str, str], *required: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {name: {"type": kind} for name, kind in properties.items()},
        "required": list(required),
    }


def register_core_tools(registry: ToolRegistry, services: CoreToolServices) -> None:
    repo = services.repository

    def timer(args: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        seconds = max(1, min(86_400, int(args["seconds"])))
        label = str(args.get("label", "Timer")).strip()[:120] or "Timer"
        due = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        task_id = repo.create_task(
            "timer", label, details={"seconds": seconds}, due_at=due.isoformat(), status="active"
        )
        return f"Timer started for {format_duration(seconds)}.", {"task_id": task_id, "due_at": due.isoformat()}

    registry.register(
        ToolManifest(
            "timer.start",
            "Start a bounded local timer",
            _schema({"seconds": "integer", "label": "string"}, "seconds"),
            ToolRisk.AUTO_SAFE,
            Capability.TIMER_MANAGE,
        ),
        timer,
    )

    def pomodoro(args: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        minutes = max(1, min(120, int(args.get("minutes", 25))))
        due = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        task_id = repo.create_task(
            "pomodoro",
            "Focus session",
            details={"minutes": minutes},
            due_at=due.isoformat(),
            status="active",
        )
        return f"Focus mode started for {minutes} minutes.", {"task_id": task_id, "due_at": due.isoformat()}

    registry.register(
        ToolManifest(
            "focus.start",
            "Start a Pomodoro focus session",
            _schema({"minutes": "integer"}),
            ToolRisk.AUTO_SAFE,
            Capability.TIMER_MANAGE,
        ),
        pomodoro,
    )

    def todo_add(args: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        title = str(args["title"]).strip()[:500]
        task_id = repo.create_task("todo", title)
        return f"Added todo: {title}", {"task_id": task_id}

    registry.register(
        ToolManifest(
            "todo.add",
            "Add a private local todo",
            _schema({"title": "string"}, "title"),
            ToolRisk.AUTO_SAFE,
            Capability.TODO_MANAGE,
        ),
        todo_add,
    )

    def todo_list(_args: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        tasks = repo.list_tasks(status="open", kind="todo", limit=20)
        return (
            "You have no open todos." if not tasks else f"You have {len(tasks)} open todo(s).",
            {"tasks": [{"task_id": row["task_id"], "title": row["title"]} for row in tasks]},
        )

    registry.register(
        ToolManifest(
            "todo.list",
            "List private local todos",
            OBJECT_SCHEMA,
            ToolRisk.AUTO_SAFE,
            Capability.TODO_MANAGE,
        ),
        todo_list,
    )

    def todo_complete(args: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        identifier = str(args["task_id"])
        changed = repo.update_task_status(identifier, "done")
        return ("Todo completed." if changed else "I could not find that todo.", {"updated": changed})

    registry.register(
        ToolManifest(
            "todo.complete",
            "Complete a private local todo",
            _schema({"task_id": "string"}, "task_id"),
            ToolRisk.AUTO_SAFE,
            Capability.TODO_MANAGE,
        ),
        todo_complete,
    )

    def reminder(args: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        title = str(args["title"]).strip()[:500]
        seconds = max(1, min(31_536_000, int(args["seconds"])))
        due = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        task_id = repo.create_task("reminder", title, due_at=due.isoformat())
        return f"Reminder created for {format_duration(seconds)} from now.", {"task_id": task_id, "due_at": due.isoformat()}

    registry.register(
        ToolManifest(
            "reminder.create",
            "Create a local reminder",
            _schema({"title": "string", "seconds": "integer"}, "title", "seconds"),
            ToolRisk.AUTO_SAFE,
            Capability.REMINDER_MANAGE,
        ),
        reminder,
    )

    def note(args: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        title = str(args.get("title", "Note")).strip()[:200] or "Note"
        text = str(args["text"]).strip()[:4000]
        task_id = repo.create_task("note", title, details={"text": text})
        return f"Saved note: {title}", {"task_id": task_id}

    registry.register(
        ToolManifest(
            "note.create",
            "Create a private local note",
            _schema({"title": "string", "text": "string"}, "text"),
            ToolRisk.AUTO_SAFE,
            Capability.NOTE_MANAGE,
        ),
        note,
    )

    def read_file(args: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        path = Path(str(args["path"])).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() not in {
            ".txt", ".md", ".json", ".yaml", ".yml", ".toml", ".py", ".log"
        }:
            raise ValueError("Only an existing selected text file can be read")
        if path.stat().st_size > 256 * 1024:
            raise ValueError("Selected file exceeds the 256 KiB limit")
        content = path.read_text(encoding="utf-8", errors="replace")[:32_000]
        return f"Read {path.name}.", {"name": path.name, "content": content}

    registry.register(
        ToolManifest(
            "file.read",
            "Read one user-approved text file",
            _schema({"path": "string"}, "path"),
            ToolRisk.CONFIRM_ONCE,
            Capability.FILESYSTEM_READ,
        ),
        read_file,
        scope_builder=approved_path_scope,
    )

    def search_files(args: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        root = Path(str(args["path"])).expanduser().resolve()
        query = str(args["query"]).casefold().strip()
        if not root.is_dir() or not query:
            raise ValueError("An approved directory and non-empty query are required")
        matches: list[str] = []
        inspected = 0
        for candidate in root.rglob("*"):
            if inspected >= 5000 or len(matches) >= 50:
                break
            inspected += 1
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if not resolved.is_relative_to(root) or not resolved.is_file():
                continue
            if query in candidate.name.casefold():
                matches.append(str(candidate.relative_to(root)))
        return f"Found {len(matches)} matching file(s).", {"matches": matches, "truncated": len(matches) >= 50}

    registry.register(
        ToolManifest(
            "file.search",
            "Search names inside one approved directory",
            _schema({"path": "string", "query": "string"}, "path", "query"),
            ToolRisk.CONFIRM_ONCE,
            Capability.FILESYSTEM_READ,
        ),
        search_files,
        scope_builder=approved_path_scope,
    )

    def clipboard(_args: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        if services.clipboard_reader is None:
            raise RuntimeError("Clipboard adapter is unavailable")
        text = services.clipboard_reader().strip()
        if not text:
            return "The clipboard is empty.", {"summary": ""}
        summary = " ".join(text.split())[:500]
        return "I summarized the authorized clipboard text.", {"summary": summary}

    registry.register(
        ToolManifest(
            "clipboard.summarize",
            "Summarize clipboard text after explicit consent",
            OBJECT_SCHEMA,
            ToolRisk.CONFIRM_EACH,
            Capability.CLIPBOARD_READ,
        ),
        clipboard,
    )

    def open_application(args: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        application = str(args["application"]).strip()
        if services.application_opener is None or not services.application_opener(application):
            raise RuntimeError("The approved application could not be opened")
        return f"Opened {application}.", {"application": application}

    registry.register(
        ToolManifest(
            "application.open",
            "Open an allowlisted desktop application",
            _schema({"application": "string"}, "application"),
            ToolRisk.CONFIRM_EACH,
            Capability.APPLICATION_OPEN,
        ),
        open_application,
        scope_builder=lambda args: {"application": str(args["application"])},
    )


class ToolIntentParser:
    """Conservative deterministic parser; ambiguous text remains ordinary chat."""

    _DURATION = re.compile(r"(?i)\b(\d{1,4})\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b")

    def parse(self, message: str) -> ToolInvocation | None:
        text = " ".join(message.strip().split())
        lower = text.casefold()
        duration = self._parse_duration(text)
        if duration and any(phrase in lower for phrase in ("set a timer", "start a timer", "timer for")):
            return ToolInvocation("timer.start", {"seconds": duration, "label": "Timer"}, explicit_user_action=True, reason=text)
        if any(phrase in lower for phrase in ("start pomodoro", "start focus", "focus for")):
            minutes = max(1, (duration or 25 * 60) // 60)
            return ToolInvocation("focus.start", {"minutes": minutes}, explicit_user_action=True, reason=text)
        if lower.startswith(("add todo ", "add a todo ", "todo: ")):
            title = re.sub(r"(?i)^(?:add\s+(?:a\s+)?todo|todo:)\s*", "", text)
            return ToolInvocation("todo.add", {"title": title}, explicit_user_action=True, reason=text)
        if lower in {"list todos", "show todos", "what are my todos"}:
            return ToolInvocation("todo.list", {}, explicit_user_action=True, reason=text)
        if lower.startswith(("save note ", "note: ")):
            note = re.sub(r"(?i)^(?:save\s+note|note:)\s*", "", text)
            return ToolInvocation("note.create", {"text": note, "title": "Pet note"}, explicit_user_action=True, reason=text)
        if lower in {"summarize clipboard", "summarize my clipboard", "read my clipboard"}:
            return ToolInvocation("clipboard.summarize", {}, explicit_user_action=True, reason=text)
        if lower.startswith("read file "):
            path = text[len("read file ") :].strip().strip('"')
            return ToolInvocation("file.read", {"path": path}, explicit_user_action=True, reason=text)
        match = re.match(r"(?i)^search files in (.+?) for (.+)$", text)
        if match:
            return ToolInvocation(
                "file.search",
                {"path": match.group(1).strip().strip('"'), "query": match.group(2).strip()},
                explicit_user_action=True,
                reason=text,
            )
        if lower.startswith(("open application ", "open app ")):
            application = re.sub(r"(?i)^open\s+(?:application|app)\s+", "", text).strip()
            return ToolInvocation(
                "application.open",
                {"application": application},
                explicit_user_action=True,
                reason=text,
            )
        if duration and lower.startswith("remind me"):
            title = re.sub(r"(?i)^remind me(?:\s+in\s+[^ ]+\s+[^ ]+)?\s+(?:to\s+)?", "", text)
            return ToolInvocation("reminder.create", {"title": title or "Reminder", "seconds": duration}, explicit_user_action=True, reason=text)
        return None

    def _parse_duration(self, text: str) -> int | None:
        match = self._DURATION.search(text)
        if not match:
            return None
        value = int(match.group(1))
        unit = match.group(2).casefold()
        if unit.startswith(("hour", "hr")):
            return value * 3600
        if unit.startswith(("minute", "min")):
            return value * 60
        return value


def format_duration(seconds: int) -> str:
    if seconds % 3600 == 0:
        return f"{seconds // 3600} hour(s)"
    if seconds % 60 == 0:
        return f"{seconds // 60} minute(s)"
    return f"{seconds} second(s)"
