from __future__ import annotations

import json
import sqlite3
import time
from datetime import date
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from vla_pet.async_tools import AsyncToolExecutor
from vla_pet.builtin_tools import CoreToolServices, ToolIntentParser, register_core_tools
from vla_pet.life import LifeContext, LifeEngine, LifeIntent
from vla_pet.memory import MemoryManager, MemoryTier
from vla_pet.permissions import Capability, PermissionBroker, PermissionLifetime
from vla_pet.persistence import SCHEMA_VERSION, StateRepository
from vla_pet.progression import ProgressionEngine
from vla_pet.state import PetRuntimeState
from vla_pet.tool_runtime import (
    ToolHost,
    ToolInvocation,
    ToolManifest,
    ToolRegistry,
    ToolRisk,
)


def test_v1_state_migrates_v0_snapshot_and_progression_is_positive() -> None:
    state = PetRuntimeState.from_snapshot(
        {
            "schema_version": 1,
            "x": 0.7,
            "needs": {"energy": 0.4, "boredom": 0.2, "social": 0.3, "curiosity": 0.8},
            "emotion": {"valence": 0.2, "arousal": 0.1, "affection": 0.4, "tag": "content"},
        }
    )
    assert state.schema_version == 3 and state.x == 0.7
    progression = ProgressionEngine()
    for _ in range(20):
        progression.interact(state)
    assert state.progression.level >= 2
    assert progression.use_item(state, "snack")
    first = progression.daily_check_in(state, today=date(2026, 7, 19))
    second = progression.daily_check_in(state, today=date(2026, 7, 19))
    assert first.xp_awarded == 10 and second.xp_awarded == 0


def test_life_context_adds_focus_inspect_and_comfort_utilities() -> None:
    state = PetRuntimeState()
    life = LifeEngine()
    decision = life.tick(state, 0.2, context=LifeContext(focus_active=True))
    assert decision is not None and decision.intent is LifeIntent.FOCUS
    state.needs.curiosity = 1.0
    decision = life.tick(state, 0.2, context=LifeContext(recent_notification=True))
    assert decision is not None and decision.scores[LifeIntent.INSPECT] > 0.7


def test_v1_database_migrates_v1_with_backup(tmp_path: Path) -> None:
    database = tmp_path / "pet.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE pet_state (singleton_id INTEGER PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE conversation_turns (id INTEGER PRIMARY KEY, role TEXT, text TEXT, created_at TEXT);
        CREATE TABLE meaningful_events (id INTEGER PRIMARY KEY, category TEXT, payload_json TEXT, importance REAL, expires_at TEXT, created_at TEXT);
        PRAGMA user_version = 1;
        """
    )
    connection.close()
    with StateRepository(database) as repository:
        assert repository.get_setting("missing") is None
    check = sqlite3.connect(database)
    assert check.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert check.execute("SELECT name FROM sqlite_master WHERE name='memory_items'").fetchone()
    check.close()
    assert database.with_name("pet.db.pre-v3-from-v1.bak").is_file()


def test_memory_task_audit_plugin_and_backup_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "data" / "pet.db"
    backup = tmp_path / "backup" / "pet.db"
    with StateRepository(database) as repository:
        memory = MemoryManager(repository)
        identifiers = memory.remember_from_user("Please call me Quan and I prefer concise answers")
        assert identifiers
        first = memory.remember_from_user("I prefer concise answers")
        second = memory.remember_from_user("I prefer concise answers")
        assert first == second
        rows = memory.retrieve("concise", tiers=(MemoryTier.PROFILE,))
        assert rows and "concise" in rows[0]["summary"].lower()
        task_id = repository.create_task("todo", "Finish v1")
        assert repository.list_tasks(status="open")[0]["task_id"] == task_id
        repository.record_tool_audit(
            {
                "tool_name": "timer.start",
                "subject": "core",
                "capability": "timer_manage",
                "decision": "allow",
                "status": "ok",
            }
        )
        assert repository.recent_tool_audit()[0]["tool_name"] == "timer.start"
        assert repository.recent_tool_audit()[0]["input_keys"] == []
        repository.set_plugin_value("plugin.test", "score", {"value": 2}, quota_bytes=100)
        assert repository.get_plugin_value("plugin.test", "score")["value"] == 2
        repository.backup(backup)
    restored = tmp_path / "restored" / "pet.db"
    StateRepository.restore(backup, restored)
    with StateRepository(restored) as repository:
        assert repository.search_memories("concise")


def test_memory_rejects_secret_extraction_and_redacts_email(tmp_path: Path) -> None:
    with StateRepository(tmp_path / "pet.db") as repository:
        memory = MemoryManager(repository)
        assert memory.extract_user_candidates("my API key: abc123") == ()
        identifier = memory.remember_shared_event("Met user@example.com for a cheerful check-in")
        row = repository.search_memories("cheerful")[0]
        assert row["memory_id"] == identifier and "user@example.com" not in row["summary"]


def test_restart_recalls_preference_task_and_shared_event_without_raw_chat(tmp_path: Path) -> None:
    database = tmp_path / "pet.db"
    with StateRepository(database) as repository:
        memory = MemoryManager(repository)
        memory.remember_from_user("I prefer quiet concise replies")
        memory.remember_shared_event("We celebrated the first complete v1 build")
        repository.create_task("todo", "Run the live acceptance")
        assert repository.recent_conversation() == ()
    with StateRepository(database) as repository:
        memory = MemoryManager(repository)
        assert memory.retrieve("quiet concise", tiers=(MemoryTier.PROFILE,))
        assert memory.retrieve("complete v1 build", tiers=(MemoryTier.EPISODIC,))
        assert repository.list_tasks(kind="todo")[0]["title"] == "Run the live acceptance"
        assert repository.recent_conversation() == ()


def test_all_persistent_memory_tiers_have_explicit_paths(tmp_path: Path) -> None:
    with StateRepository(tmp_path / "pet.db") as repository:
        memory = MemoryManager(repository)
        memory.remember_from_user("Remember that the pet lives on monitor one")
        memory.remember_relationship("Companion relationship reached level 2")
        memory.remember_procedure("Successful companion workflow: timer.start")
        assert memory.retrieve("monitor one", tiers=(MemoryTier.SEMANTIC,))
        assert memory.retrieve("level 2", tiers=(MemoryTier.RELATIONSHIP,))
        assert memory.retrieve("timer start", tiers=(MemoryTier.PROCEDURAL,))


def test_permission_scope_denial_prevents_tool_handler_execution(tmp_path: Path) -> None:
    broker = PermissionBroker()
    broker.grant(
        Capability.FILESYSTEM_READ,
        lifetime=PermissionLifetime.SESSION,
        scope={"path": str(tmp_path / "allowed")},
    )
    called: list[bool] = []
    registry = ToolRegistry()
    registry.register(
        ToolManifest(
            "test.read",
            "test",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            ToolRisk.CONFIRM_ONCE,
            Capability.FILESYSTEM_READ,
        ),
        lambda _args: called.append(True) or "ran",
        scope_builder=lambda args: {"path": args["path"]},
    )
    with StateRepository(tmp_path / "audit.db") as repository:
        host = ToolHost(registry, broker, repository=repository)
        denied = host.invoke(ToolInvocation("test.read", {"path": str(tmp_path / "outside")}))
        assert not denied.ok and called == []
        assert repository.recent_tool_audit()[0]["status"] == "denied"
        allowed = host.invoke(ToolInvocation("test.read", {"path": str(tmp_path / "allowed" / "a.txt")}))
        assert allowed.ok and called == [True]
        audit = repository.recent_tool_audit()[0]
        assert audit["scope"]["permission_lifetime"] == "session"
        assert audit["scope"]["permission_grant_id"].startswith("perm_")


def test_core_tool_loop_and_conservative_intent_parser(tmp_path: Path) -> None:
    with StateRepository(tmp_path / "pet.db") as repository:
        registry = ToolRegistry()
        register_core_tools(registry, CoreToolServices(repository))
        broker = PermissionBroker(
            {
                Capability.TIMER_MANAGE,
                Capability.TODO_MANAGE,
                Capability.REMINDER_MANAGE,
                Capability.NOTE_MANAGE,
            }
        )
        host = ToolHost(registry, broker, repository=repository)
        parser = ToolIntentParser()
        invocation = parser.parse("set a timer for 2 minutes")
        assert invocation is not None
        result = host.invoke(invocation)
        assert result.ok and repository.list_tasks(kind="timer")
        assert parser.parse("tell me about the concept of time") is None
        note = parser.parse("note: v1 tool loop works")
        assert note is not None and host.invoke(note).ok


def test_export_contains_v1_private_tables(tmp_path: Path) -> None:
    export = tmp_path / "export.json"
    with StateRepository(tmp_path / "pet.db") as repository:
        repository.export(export)
    payload = json.loads(export.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 3
    assert "habitat_state" in payload
    assert {"memory_items", "tasks", "tool_audit", "plugin_state"} <= payload.keys()


def test_async_tool_executor_keeps_tool_work_off_the_caller(tmp_path: Path) -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    broker = PermissionBroker({Capability.TIMER_MANAGE})
    executor = AsyncToolExecutor(tmp_path / "pet.db", broker)
    completed: list[object] = []
    executor.finished.connect(lambda _invocation, result: completed.append(result))
    invocation = ToolInvocation(
        "timer.start",
        {"seconds": 1, "label": "async"},
        explicit_user_action=True,
    )
    started = time.monotonic()
    assert executor.submit(invocation)
    assert time.monotonic() - started < 0.1
    deadline = time.monotonic() + 3.0
    while not completed and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    executor.close()
    assert completed and completed[0].ok
    with StateRepository(tmp_path / "pet.db") as repository:
        assert repository.list_tasks(kind="timer")
