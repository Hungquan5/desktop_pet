from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from vla_pet.errors import ErrorCategory, PetError
from vla_pet.paths import ensure_private_directory
from vla_pet.state import PetRuntimeState

SCHEMA_VERSION = 2


class StateRepository(AbstractContextManager["StateRepository"]):
    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        self.path = path
        self.read_only = read_only
        if not read_only:
            ensure_private_directory(path.parent)
        try:
            target = f"file:{path}?mode=ro" if read_only else str(path)
            self._db = sqlite3.connect(target, uri=read_only, timeout=5.0)
            self._db.row_factory = sqlite3.Row
            if not read_only:
                path.chmod(0o600)
                self._db.execute("PRAGMA journal_mode=WAL")
                self._migrate()
                self.prune_expired_events()
                self._secure_database_files()
        except sqlite3.Error as exc:
            raise PetError(
                ErrorCategory.PERSISTENCE,
                "database.open_failed",
                f"Could not open state database: {exc}",
            ) from exc

    def _migrate(self) -> None:
        version = int(self._db.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise PetError(
                ErrorCategory.PERSISTENCE,
                "database.schema_too_new",
                f"Database schema {version} is newer than supported schema {SCHEMA_VERSION}",
            )
        if 0 < version < SCHEMA_VERSION:
            self._backup_before_migration(version)
        if version == 0:
            with self._db:
                self._db.executescript(
                    """
                    CREATE TABLE settings (
                        key TEXT PRIMARY KEY,
                        value_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE pet_state (
                        singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                        value_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE conversation_turns (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        role TEXT NOT NULL CHECK (role IN ('user', 'pet')),
                        text TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE meaningful_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        category TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        importance REAL NOT NULL DEFAULT 0.5,
                        expires_at TEXT,
                        created_at TEXT NOT NULL
                    );
                    PRAGMA user_version = 1;
                    """
                )
            version = 1
        if version == 1:
            with self._db:
                self._db.executescript(
                    """
                    CREATE TABLE memory_items (
                        memory_id TEXT PRIMARY KEY,
                        tier TEXT NOT NULL CHECK (
                            tier IN ('episodic', 'semantic', 'profile', 'task',
                                     'relationship', 'procedural')
                        ),
                        kind TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        details_json TEXT NOT NULL DEFAULT '{}',
                        dedupe_key TEXT NOT NULL UNIQUE,
                        salience REAL NOT NULL DEFAULT 0.5,
                        tags_json TEXT NOT NULL DEFAULT '[]',
                        expires_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE VIRTUAL TABLE memory_fts USING fts5(
                        memory_id UNINDEXED, summary, tags
                    );
                    CREATE TABLE tasks (
                        task_id TEXT PRIMARY KEY,
                        kind TEXT NOT NULL CHECK (
                            kind IN ('todo', 'reminder', 'note', 'timer', 'pomodoro')
                        ),
                        title TEXT NOT NULL,
                        details_json TEXT NOT NULL DEFAULT '{}',
                        status TEXT NOT NULL DEFAULT 'open' CHECK (
                            status IN ('open', 'active', 'done', 'cancelled')
                        ),
                        due_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE tool_audit (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        invocation_id TEXT NOT NULL UNIQUE,
                        tool_name TEXT NOT NULL,
                        subject TEXT NOT NULL,
                        capability TEXT NOT NULL,
                        scope_json TEXT NOT NULL,
                        decision TEXT NOT NULL,
                        status TEXT NOT NULL,
                        duration_ms REAL NOT NULL DEFAULT 0,
                        error_code TEXT NOT NULL DEFAULT '',
                        trace_id TEXT NOT NULL,
                        risk TEXT NOT NULL,
                        reason_chars INTEGER NOT NULL DEFAULT 0,
                        input_keys_json TEXT NOT NULL DEFAULT '[]',
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE plugin_state (
                        namespace TEXT NOT NULL,
                        key TEXT NOT NULL,
                        value_json TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY(namespace, key)
                    );
                    CREATE INDEX memory_items_tier_updated
                        ON memory_items(tier, updated_at DESC);
                    CREATE INDEX tasks_status_due ON tasks(status, due_at);
                    CREATE INDEX tool_audit_created ON tool_audit(created_at DESC);
                    PRAGMA user_version = 2;
                    """
                )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def set_setting(self, key: str, value: Any) -> None:
        self._require_writable()
        with self._db:
            self._db.execute(
                """INSERT INTO settings(key, value_json, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,
                   updated_at=excluded.updated_at""",
                (key, json.dumps(value, ensure_ascii=False), self._now()),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self._db.execute("SELECT value_json FROM settings WHERE key = ?", (key,)).fetchone()
        return default if row is None else json.loads(row[0])

    def save_state(self, state: PetRuntimeState) -> None:
        self._require_writable()
        with self._db:
            self._db.execute(
                """INSERT INTO pet_state(singleton_id, value_json, updated_at) VALUES (1, ?, ?)
                   ON CONFLICT(singleton_id) DO UPDATE SET value_json=excluded.value_json,
                   updated_at=excluded.updated_at""",
                (json.dumps(state.snapshot(), ensure_ascii=False), self._now()),
            )

    def load_state(self) -> PetRuntimeState:
        row = self._db.execute("SELECT value_json FROM pet_state WHERE singleton_id = 1").fetchone()
        if row is None:
            return PetRuntimeState()
        try:
            return PetRuntimeState.from_snapshot(json.loads(row[0]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return PetRuntimeState()

    def append_conversation(self, role: str, text: str) -> None:
        self._require_writable()
        if role not in {"user", "pet"} or not text.strip():
            raise ValueError("Invalid conversation turn")
        with self._db:
            self._db.execute(
                "INSERT INTO conversation_turns(role, text, created_at) VALUES (?, ?, ?)",
                (role, text[:4000], self._now()),
            )

    def recent_conversation(self, limit: int = 12) -> tuple[tuple[str, str], ...]:
        rows = self._db.execute(
            "SELECT role, text FROM conversation_turns ORDER BY id DESC LIMIT ?",
            (max(1, min(100, limit)),),
        ).fetchall()
        return tuple((str(row["role"]), str(row["text"])) for row in reversed(rows))

    def clear_conversations(self) -> None:
        self._require_writable()
        with self._db:
            self._db.execute("DELETE FROM conversation_turns")

    def upsert_memory(
        self,
        *,
        tier: str,
        kind: str,
        summary: str,
        dedupe_key: str,
        salience: float = 0.5,
        tags: tuple[str, ...] = (),
        details: dict[str, Any] | None = None,
        expires_at: str | None = None,
        memory_id: str | None = None,
    ) -> str:
        self._require_writable()
        now = self._now()
        identifier = memory_id or f"mem_{uuid4().hex}"
        normalized_tags = tuple(dict.fromkeys(tag.strip().lower() for tag in tags if tag.strip()))
        with self._db:
            existing = self._db.execute(
                "SELECT memory_id FROM memory_items WHERE dedupe_key = ?", (dedupe_key,)
            ).fetchone()
            if existing is not None:
                identifier = str(existing[0])
            self._db.execute(
                """INSERT INTO memory_items(
                       memory_id, tier, kind, summary, details_json, dedupe_key,
                       salience, tags_json, expires_at, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(dedupe_key) DO UPDATE SET
                       tier=excluded.tier, kind=excluded.kind, summary=excluded.summary,
                       details_json=excluded.details_json,
                       salience=MAX(memory_items.salience, excluded.salience),
                       tags_json=excluded.tags_json, expires_at=excluded.expires_at,
                       updated_at=excluded.updated_at""",
                (
                    identifier,
                    tier,
                    kind,
                    summary[:1000],
                    json.dumps(details or {}, ensure_ascii=False),
                    dedupe_key,
                    min(1.0, max(0.0, float(salience))),
                    json.dumps(normalized_tags, ensure_ascii=False),
                    expires_at,
                    now,
                    now,
                ),
            )
            self._db.execute("DELETE FROM memory_fts WHERE memory_id = ?", (identifier,))
            self._db.execute(
                "INSERT INTO memory_fts(memory_id, summary, tags) VALUES (?, ?, ?)",
                (identifier, summary[:1000], " ".join(normalized_tags)),
            )
        return identifier

    def search_memories(
        self,
        query: str = "",
        *,
        tiers: tuple[str, ...] = (),
        limit: int = 12,
    ) -> tuple[dict[str, Any], ...]:
        now = self._now()
        parameters: list[Any] = [now]
        where = ["(m.expires_at IS NULL OR m.expires_at > ?)"]
        if tiers:
            where.append(f"m.tier IN ({','.join('?' for _ in tiers)})")
            parameters.extend(tiers)
        tokens = re.findall(r"[\w-]+", query.lower(), flags=re.UNICODE)
        join = ""
        rank = "0.0"
        if tokens:
            join = "JOIN memory_fts f ON f.memory_id = m.memory_id"
            where.append("memory_fts MATCH ?")
            parameters.append(" OR ".join(f'\"{token}\"' for token in tokens[:12]))
            rank = "bm25(memory_fts)"
        parameters.append(max(1, min(200, int(limit))))
        rows = self._db.execute(
            f"""SELECT m.*, {rank} AS search_rank
                FROM memory_items m {join}
                WHERE {' AND '.join(where)}
                ORDER BY m.salience DESC, search_rank ASC, m.updated_at DESC
                LIMIT ?""",
            parameters,
        ).fetchall()
        return tuple(self._decode_memory(row) for row in rows)

    def delete_memory(self, memory_id: str) -> bool:
        self._require_writable()
        with self._db:
            cursor = self._db.execute("DELETE FROM memory_items WHERE memory_id = ?", (memory_id,))
            self._db.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
        return cursor.rowcount > 0

    def clear_memories(self, *, tier: str | None = None) -> int:
        self._require_writable()
        with self._db:
            if tier:
                ids = [
                    str(row[0])
                    for row in self._db.execute(
                        "SELECT memory_id FROM memory_items WHERE tier = ?", (tier,)
                    )
                ]
                cursor = self._db.execute("DELETE FROM memory_items WHERE tier = ?", (tier,))
                self._db.executemany(
                    "DELETE FROM memory_fts WHERE memory_id = ?", ((item,) for item in ids)
                )
            else:
                cursor = self._db.execute("DELETE FROM memory_items")
                self._db.execute("DELETE FROM memory_fts")
        return max(0, cursor.rowcount)

    def create_task(
        self,
        kind: str,
        title: str,
        *,
        details: dict[str, Any] | None = None,
        due_at: str | None = None,
        status: str = "open",
    ) -> str:
        self._require_writable()
        identifier = f"task_{uuid4().hex}"
        now = self._now()
        with self._db:
            self._db.execute(
                """INSERT INTO tasks(
                       task_id, kind, title, details_json, status, due_at, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    identifier,
                    kind,
                    title.strip()[:500],
                    json.dumps(details or {}, ensure_ascii=False),
                    status,
                    due_at,
                    now,
                    now,
                ),
            )
        return identifier

    def list_tasks(
        self, *, status: str | None = None, kind: str | None = None, limit: int = 100
    ) -> tuple[dict[str, Any], ...]:
        where: list[str] = []
        parameters: list[Any] = []
        if status:
            where.append("status = ?")
            parameters.append(status)
        if kind:
            where.append("kind = ?")
            parameters.append(kind)
        parameters.append(max(1, min(500, int(limit))))
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        rows = self._db.execute(
            f"SELECT * FROM tasks {clause} ORDER BY due_at IS NULL, due_at, created_at LIMIT ?",
            parameters,
        ).fetchall()
        return tuple(self._decode_task(row) for row in rows)

    def update_task_status(self, task_id: str, status: str) -> bool:
        self._require_writable()
        with self._db:
            cursor = self._db.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                (status, self._now(), task_id),
            )
        return cursor.rowcount > 0

    def record_tool_audit(self, entry: dict[str, Any]) -> str:
        self._require_writable()
        invocation_id = str(entry.get("invocation_id") or f"tool_{uuid4().hex}")
        with self._db:
            self._db.execute(
                """INSERT INTO tool_audit(
                       invocation_id, tool_name, subject, capability, scope_json,
                       decision, status, duration_ms, error_code, trace_id, risk,
                       reason_chars, input_keys_json, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    invocation_id,
                    str(entry.get("tool_name", "unknown")),
                    str(entry.get("subject", "core")),
                    str(entry.get("capability", "")),
                    json.dumps(entry.get("scope", {}), ensure_ascii=False),
                    str(entry.get("decision", "deny")),
                    str(entry.get("status", "denied")),
                    max(0.0, float(entry.get("duration_ms", 0.0))),
                    str(entry.get("error_code", "")),
                    str(entry.get("trace_id", "")),
                    str(entry.get("risk", "")),
                    max(0, int(entry.get("reason_chars", 0))),
                    json.dumps(entry.get("input_keys", []), ensure_ascii=False),
                    self._now(),
                ),
            )
        return invocation_id

    def recent_tool_audit(self, limit: int = 100) -> tuple[dict[str, Any], ...]:
        rows = self._db.execute(
            "SELECT * FROM tool_audit ORDER BY id DESC LIMIT ?",
            (max(1, min(1000, int(limit))),),
        ).fetchall()
        return tuple(
            {
                **dict(row),
                "scope": json.loads(row["scope_json"]),
                "input_keys": json.loads(row["input_keys_json"]),
            }
            for row in rows
        )

    def set_plugin_value(
        self, namespace: str, key: str, value: Any, *, quota_bytes: int = 1_048_576
    ) -> None:
        self._require_writable()
        encoded = json.dumps(value, ensure_ascii=False)
        size = len(encoded.encode("utf-8"))
        existing = int(
            self._db.execute(
                "SELECT COALESCE(SUM(size_bytes), 0) FROM plugin_state WHERE namespace = ? AND key != ?",
                (namespace, key),
            ).fetchone()[0]
        )
        if existing + size > max(0, int(quota_bytes)):
            raise PetError(
                ErrorCategory.PERSISTENCE,
                "plugin.storage.quota_exceeded",
                f"Plugin storage quota exceeded for {namespace}",
            )
        with self._db:
            self._db.execute(
                """INSERT INTO plugin_state(namespace, key, value_json, size_bytes, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(namespace, key) DO UPDATE SET
                       value_json=excluded.value_json, size_bytes=excluded.size_bytes,
                       updated_at=excluded.updated_at""",
                (namespace, key, encoded, size, self._now()),
            )

    def get_plugin_value(self, namespace: str, key: str, default: Any = None) -> Any:
        row = self._db.execute(
            "SELECT value_json FROM plugin_state WHERE namespace = ? AND key = ?",
            (namespace, key),
        ).fetchone()
        return default if row is None else json.loads(row[0])

    def reset_state(self) -> None:
        self._require_writable()
        with self._db:
            self._db.execute("DELETE FROM pet_state")

    def record_event(
        self,
        category: str,
        payload: dict[str, Any],
        *,
        importance: float = 0.5,
        expires_at: str | None = None,
    ) -> None:
        self._require_writable()
        with self._db:
            self._db.execute(
                """INSERT INTO meaningful_events
                   (category, payload_json, importance, expires_at, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    category,
                    json.dumps(payload, ensure_ascii=False, default=str),
                    min(1.0, max(0.0, importance)),
                    expires_at,
                    self._now(),
                ),
            )

    def prune_expired_events(self, *, now: str | None = None) -> int:
        self._require_writable()
        cutoff = now or self._now()
        with self._db:
            cursor = self._db.execute(
                "DELETE FROM meaningful_events WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (cutoff,),
            )
        return max(0, cursor.rowcount)

    def export(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "settings": [dict(row) for row in self._db.execute("SELECT * FROM settings")],
            "pet_state": [dict(row) for row in self._db.execute("SELECT * FROM pet_state")],
            "conversation_turns": [
                dict(row) for row in self._db.execute("SELECT * FROM conversation_turns")
            ],
            "meaningful_events": [
                dict(row) for row in self._db.execute("SELECT * FROM meaningful_events")
            ],
            "memory_items": [dict(row) for row in self._db.execute("SELECT * FROM memory_items")],
            "tasks": [dict(row) for row in self._db.execute("SELECT * FROM tasks")],
            "tool_audit": [dict(row) for row in self._db.execute("SELECT * FROM tool_audit")],
            "plugin_state": [dict(row) for row in self._db.execute("SELECT * FROM plugin_state")],
        }
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
        destination.chmod(0o600)
        return destination

    def backup(self, destination: Path) -> Path:
        self._require_writable()
        ensure_private_directory(destination.parent)
        target = sqlite3.connect(destination)
        try:
            self._db.backup(target)
        finally:
            target.close()
        destination.chmod(0o600)
        return destination

    @staticmethod
    def restore(source: Path, destination: Path) -> Path:
        if not source.is_file():
            raise PetError(ErrorCategory.PERSISTENCE, "backup.missing", "Backup file does not exist")
        check = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        try:
            integrity = str(check.execute("PRAGMA integrity_check").fetchone()[0])
            version = int(check.execute("PRAGMA user_version").fetchone()[0])
            if integrity != "ok" or version > SCHEMA_VERSION:
                raise PetError(
                    ErrorCategory.PERSISTENCE,
                    "backup.invalid",
                    "Backup failed integrity or schema validation",
                )
            ensure_private_directory(destination.parent)
            temporary = destination.with_suffix(destination.suffix + ".restore")
            restored = sqlite3.connect(temporary)
            try:
                check.backup(restored)
            finally:
                restored.close()
            temporary.chmod(0o600)
            os.replace(temporary, destination)
            destination.chmod(0o600)
        finally:
            check.close()
        return destination

    def _backup_before_migration(self, version: int) -> None:
        destination = self.path.with_name(f"{self.path.name}.pre-v{SCHEMA_VERSION}-from-v{version}.bak")
        target = sqlite3.connect(destination)
        try:
            self._db.backup(target)
        finally:
            target.close()
        destination.chmod(0o600)

    @staticmethod
    def _decode_memory(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["details"] = json.loads(value.pop("details_json"))
        value["tags"] = tuple(json.loads(value.pop("tags_json")))
        return value

    @staticmethod
    def _decode_task(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["details"] = json.loads(value.pop("details_json"))
        return value

    def _secure_database_files(self) -> None:
        for candidate in (self.path, Path(f"{self.path}-wal"), Path(f"{self.path}-shm")):
            if candidate.exists():
                candidate.chmod(0o600)

    def _require_writable(self) -> None:
        if self.read_only:
            raise PetError(
                ErrorCategory.PERSISTENCE,
                "database.read_only",
                "Persistence writes are disabled in safe mode",
            )

    def close(self) -> None:
        self._db.close()
        if not self.read_only:
            self._secure_database_files()

    def __exit__(self, *_args: object) -> None:
        self.close()
