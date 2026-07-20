from __future__ import annotations

import json
import stat
import time
from pathlib import Path

import pytest

from vla_pet.ai_orchestrator import AIOrchestrator
from vla_pet.animation import AnimationController
from vla_pet.character import (
    CharacterPack,
    default_character_directory,
    load_character_or_default,
)
from vla_pet.contracts import ChatRequest
from vla_pet.diagnostics import collect_diagnostics
from vla_pet.errors import ErrorCategory, PetError
from vla_pet.events import EventBus, EventPriority, EventSource, PetEvent, UserInteractionEvent
from vla_pet.life import LifeEngine, LifeIntent
from vla_pet.paths import AppPaths
from vla_pet.permissions import Capability, PermissionLifetime, PermissionPolicy
from vla_pet.persistence import StateRepository
from vla_pet.runtime import RuntimeController
from vla_pet.session_log import SessionLogger
from vla_pet.state import PetRuntimeState
from vla_pet.worker import WorkerConfig


def test_xdg_paths_do_not_depend_on_working_directory(tmp_path: Path) -> None:
    paths = AppPaths.discover(
        {
            "HOME": str(tmp_path / "home"),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "XDG_STATE_HOME": str(tmp_path / "state"),
        }
    )
    assert paths.database == tmp_path / "data" / "vla-pet" / "pet.db"
    paths.ensure()
    assert all(path.is_dir() for path in (paths.config, paths.data, paths.cache, paths.state))
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o700
        for path in (paths.config, paths.data, paths.cache, paths.state)
    )


def test_windows_and_macos_paths_keep_user_data_outside_install_prefix(tmp_path: Path) -> None:
    windows = AppPaths.discover(
        {
            "HOME": str(tmp_path / "home"),
            "APPDATA": str(tmp_path / "roaming"),
            "LOCALAPPDATA": str(tmp_path / "local"),
        },
        platform_name="win32",
    )
    assert windows.database == tmp_path / "roaming" / "vla-pet" / "pet.db"
    assert "Programs" not in str(windows.database)
    macos = AppPaths.discover(
        {"HOME": str(tmp_path / "home")},
        platform_name="darwin",
    )
    assert macos.database == tmp_path / "home" / "Library" / "Application Support" / "vla-pet" / "pet.db"


def test_typed_event_bus_and_runtime_have_one_mutation_boundary() -> None:
    bus = EventBus()
    received: list[str] = []
    unsubscribe = bus.subscribe(PetEvent, lambda event: received.append(event.name))
    runtime = RuntimeController(bus=bus)
    before = runtime.state.interaction_count
    runtime.publish(UserInteractionEvent(name="pet"))
    unsubscribe()
    runtime.publish(UserInteractionEvent(name="drop"))
    assert received == ["pet"]
    assert runtime.state.interaction_count == before + 2


def test_event_envelope_is_versioned_traceable_and_idempotent() -> None:
    bus = EventBus(idempotency_window=2)
    received: list[str] = []
    bus.subscribe(PetEvent, lambda event: received.append(event.event_id))
    first = PetEvent(
        name="screen.question.submitted",
        source=EventSource.USER,
        priority=EventPriority.HIGH,
        session_id="test-session",
        idempotency_key="screen-question-1",
    )
    duplicate = PetEvent(
        name="screen.question.submitted",
        source=EventSource.USER,
        idempotency_key="screen-question-1",
    )
    assert first.schema_version == "pet.event/v1"
    assert first.trace.span_id
    assert bus.publish(first)
    assert not bus.publish(duplicate)
    assert received == [first.event_id]


def test_event_bus_prioritizes_reentrant_events_and_bounds_backpressure() -> None:
    bus = EventBus(max_queue=8)
    received: list[str] = []

    def handler(event: PetEvent) -> None:
        received.append(event.name)
        if event.name == "root":
            bus.publish(PetEvent("low", EventSource.LIFE, priority=EventPriority.LOW))
            bus.publish(PetEvent("high", EventSource.SYSTEM, priority=EventPriority.HIGH))

    bus.subscribe(PetEvent, handler)
    bus.publish(PetEvent("root", EventSource.SYSTEM))
    assert received == ["root", "high", "low"]
    assert bus.stats == {"published": 3, "dropped": 0, "queued": 0}


def test_ai_orchestrator_deduplicates_requests_and_publishes_metadata() -> None:
    class FakeClient:
        pending_kinds = ("chat",)
        process_id = 42

        def submit(self, _kind: str, _payload: object) -> int:
            raise AssertionError("duplicate request should not reach the worker")

        def poll(self) -> list[object]:
            return []

        def timed_out(self) -> bool:
            return False

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    bus = EventBus()
    events: list[str] = []
    bus.subscribe(PetEvent, lambda event: events.append(event.name))
    orchestrator = AIOrchestrator(WorkerConfig(mock_policy=True), bus)
    orchestrator._client = FakeClient()  # type: ignore[assignment]
    assert orchestrator.submit("chat", object()) is None
    assert orchestrator.process_id == 42
    assert not orchestrator.timed_out()
    assert events == []


def test_mock_orchestrator_uses_no_process_and_keeps_worker_contract() -> None:
    orchestrator = AIOrchestrator(WorkerConfig(mock_policy=True), EventBus())
    orchestrator.start()
    assert orchestrator.process_id is None
    request_id = orchestrator.submit("chat", ChatRequest("Hello"))
    assert request_id is not None
    assert orchestrator.submit("chat", ChatRequest("Duplicate")) is None
    responses = orchestrator.poll()
    assert len(responses) == 1
    assert responses[0].ok and responses[0].provider == "mock"
    assert orchestrator.pending_kinds == ()


def test_life_engine_runs_thirty_simulated_minutes_without_ai() -> None:
    state = PetRuntimeState()
    life = LifeEngine()
    started = time.perf_counter()
    decisions = [life.tick(state, 0.1) for _ in range(18_000)]
    elapsed = time.perf_counter() - started
    assert any(decision is not None for decision in decisions)
    assert 0.0 <= state.needs.energy <= 1.0
    assert 0.0 <= state.needs.boredom <= 1.0
    assert state.active_intention
    assert elapsed < 1.0


def test_life_routines_pause_between_walks_and_offer_play_actions() -> None:
    walk = [LifeEngine.routine_action(LifeIntent.WALK, step, -1) for step in range(6)]
    assert [action.kind.value for action in walk] == [
        "walk",
        "walk",
        "idle",
        "walk",
        "walk",
        "idle",
    ]
    assert all(action.direction == -1 for action in walk)
    play = [LifeEngine.routine_action(LifeIntent.PLAY, step, 1) for step in range(4)]
    assert [action.kind.value for action in play] == ["jump", "idle", "happy", "idle"]


def test_relationship_progression_is_deterministic() -> None:
    state = PetRuntimeState()
    life = LifeEngine()
    for _ in range(10):
        life.interact(state)
    assert state.interaction_count == 10
    assert state.relationship_level == 1


def test_sleep_recovers_energy_and_eventually_unsticks_idle_state() -> None:
    state = PetRuntimeState(active_intention=LifeIntent.SLEEP.value)
    state.needs.energy = 0.0
    life = LifeEngine()
    seen_intents: set[LifeIntent] = set()
    for _ in range(1_200):
        decision = life.tick(state, 0.1)
        if decision is not None:
            seen_intents.add(decision.intent)
    assert state.needs.energy > 0.45
    assert any(intent is not LifeIntent.SLEEP for intent in seen_intents)


def test_character_manifest_and_animation_controller_load_builtin_pack() -> None:
    pack = CharacterPack.load(default_character_directory())
    assert pack.schema_version == 3
    assert pack.character_id == "momo"
    assert pack.persona.name == "Momo"
    assert pack.voice.provider == "qt-speechd"
    assert len(pack.animations) == 6
    assert {"held", "eat", "play", "sleep", "box", "think", "listen", "talk"} <= set(
        pack.expressive_animations
    )
    controller = AnimationController(pack)
    frame = Path(controller.frame(0.5))
    assert frame.is_file()
    assert controller.select(next(kind for kind in pack.animations if kind.value == "jump"), 1.0)
    assert not controller.select(next(kind for kind in pack.animations if kind.value == "walk"), 1.01)
    assert controller.select(
        next(kind for kind in pack.animations if kind.value == "idle"), 1.02, force=True
    )
    orbit = CharacterPack.load(Path(__file__).resolve().parents[1] / "characters" / "orbit")
    assert orbit.character_id == "orbit" and orbit.license == "CC0-1.0"


def test_character_manifest_rejects_parent_traversal(tmp_path: Path) -> None:
    manifest = {
        "schema_version": 1,
        "id": "unsafe",
        "animations": {
            name: {"frames": ["../secret.png"]}
            for name in ("idle", "walk", "jump", "throw", "happy", "sad")
        },
    }
    (tmp_path / "character.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PetError) as error:
        CharacterPack.load(tmp_path)
    assert error.value.category is ErrorCategory.CHARACTER_PACK
    assert error.value.code == "character.frames.unsafe_path"
    fallback = load_character_or_default(tmp_path)
    assert fallback.pack.character_id == "momo"
    assert fallback.fallback_error_code == "character.frames.unsafe_path"


def test_sqlite_state_conversation_and_export_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "data" / "pet.db"
    export_path = tmp_path / "export.json"
    state = PetRuntimeState(x=0.73, interaction_count=4)
    with StateRepository(database) as repository:
        repository.set_setting("theme", "warm")
        repository.save_state(state)
        repository.append_conversation("user", "private sentinel")
        repository.append_conversation("pet", "hello")
        repository.record_event("milestone", {"level": 2})
        repository.export(export_path)
    with StateRepository(database) as repository:
        restored = repository.load_state()
        assert restored.x == pytest.approx(0.73)
        assert restored.interaction_count == 4
        assert repository.get_setting("theme") == "warm"
        assert repository.recent_conversation()[-1] == ("pet", "hello")
        repository.clear_conversations()
        assert repository.recent_conversation() == ()
        repository.reset_state()
        assert repository.load_state().x == pytest.approx(PetRuntimeState().x)
    assert "private sentinel" in export_path.read_text(encoding="utf-8")
    assert stat.S_IMODE(database.stat().st_mode) == 0o600
    assert stat.S_IMODE(export_path.stat().st_mode) == 0o600


def test_runtime_controller_owns_repository_lifecycle(tmp_path: Path) -> None:
    database = tmp_path / "pet.db"
    runtime = RuntimeController.from_database(database)
    runtime.state.x = 0.61
    runtime.append_conversation("user", "remember me")
    runtime.close()
    restored = RuntimeController.from_database(database)
    assert restored.state.x == pytest.approx(0.61)
    assert restored.conversation_history() == (("user", "remember me"),)
    restored.close()


def test_runtime_persists_only_redacted_meaningful_event_metadata(tmp_path: Path) -> None:
    database = tmp_path / "pet.db"
    export_path = tmp_path / "events.json"
    runtime = RuntimeController.from_database(database)
    runtime.publish(
        UserInteractionEvent(
            name="chat_open",
            data={"text": "private sentinel", "gesture_count": 1},
        )
    )
    runtime.close()
    with StateRepository(database) as repository:
        repository.export(export_path)
    exported = export_path.read_text(encoding="utf-8")
    assert "private sentinel" not in exported
    assert "gesture_count" in exported


def test_expired_meaningful_events_are_pruned_on_open(tmp_path: Path) -> None:
    database = tmp_path / "pet.db"
    export_path = tmp_path / "events.json"
    with StateRepository(database) as repository:
        repository.record_event("expired", {}, expires_at="2000-01-01T00:00:00+00:00")
        repository.record_event("retained", {}, expires_at="2999-01-01T00:00:00+00:00")
    with StateRepository(database) as repository:
        repository.export(export_path)
    exported = export_path.read_text(encoding="utf-8")
    assert '"expired"' not in exported
    assert '"retained"' in exported


def test_capability_policy_enforces_safe_mode_and_explicit_screen_action() -> None:
    policy = PermissionPolicy({Capability.NOTIFICATION_MONITOR_SESSION})
    assert policy.permits(Capability.NOTIFICATION_MONITOR_SESSION)
    assert not policy.permits(Capability.SCREEN_CAPTURE_EACH_TIME)
    assert policy.permits(Capability.SCREEN_CAPTURE_EACH_TIME, explicit_user_action=True)
    safe = PermissionPolicy({Capability.NOTIFICATION_MONITOR_SESSION}, safe_mode=True)
    with pytest.raises(PetError) as error:
        safe.require(Capability.NOTIFICATION_MONITOR_SESSION)
    assert error.value.category is ErrorCategory.PERMISSION_DENIED


def test_permission_broker_consumes_once_grants_and_never_runs_denied_operation() -> None:
    policy = PermissionPolicy()
    calls: list[str] = []
    policy.grant(
        Capability.CLIPBOARD_READ,
        lifetime=PermissionLifetime.ONCE,
        scope={"selection": "clipboard"},
    )
    result = policy.run_authorized(
        Capability.CLIPBOARD_READ,
        lambda: calls.append("read") or "value",
        scope={"selection": "clipboard"},
    )
    assert result == "value"
    assert calls == ["read"]
    assert not policy.permits(
        Capability.CLIPBOARD_READ,
        scope={"selection": "clipboard"},
    )

    with pytest.raises(PetError):
        policy.run_authorized(
            Capability.SHELL_EXEC,
            lambda: calls.append("shell"),
        )
    assert calls == ["read"]

    policy.grant(Capability.NOTIFICATION_MONITOR_SESSION)
    assert policy.revoke(Capability.NOTIFICATION_MONITOR_SESSION) == 1
    assert not policy.permits(Capability.NOTIFICATION_MONITOR_SESSION)


def test_operational_log_redacts_private_text(tmp_path: Path) -> None:
    logger = SessionLogger(tmp_path, enabled=True)
    logger.write(
        "sentinel",
        text="secret-chat-value",
        notification="secret-notification-value",
        latency_s=1.2,
    )
    assert logger.path is not None
    content = logger.path.read_text(encoding="utf-8")
    assert "secret-chat-value" not in content
    assert "secret-notification-value" not in content
    record = json.loads(content)
    assert record["text"] == {"redacted": True, "length": 17}
    assert record["latency_s"] == 1.2
    assert stat.S_IMODE(logger.path.stat().st_mode) == 0o600


def test_diagnostics_reports_redacted_environment_health(tmp_path: Path) -> None:
    paths = AppPaths(
        config=tmp_path / "config",
        data=tmp_path / "data",
        cache=tmp_path / "cache",
        state=tmp_path / "state",
    ).ensure()
    report = collect_diagnostics(paths, default_character_directory())
    assert report["application"] == "momo-chan"
    assert report["checks"]["character_pack"] == {"ok": True, "id": "momo"}
    assert report["ok"]
