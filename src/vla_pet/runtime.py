from __future__ import annotations

from pathlib import Path

from vla_pet.events import EventBus, PetEvent, PlatformEvent, UserInteractionEvent
from vla_pet.habitat import HabitatController, HabitatState
from vla_pet.life import LifeContext, LifeDecision, LifeEngine
from vla_pet.memory import MemoryManager
from vla_pet.persistence import StateRepository
from vla_pet.state import PetRuntimeState


class RuntimeController:
    """Single mutation boundary for long-lived companion state."""

    def __init__(
        self,
        state: PetRuntimeState | None = None,
        *,
        bus: EventBus | None = None,
        life: LifeEngine | None = None,
        repository: StateRepository | None = None,
        memory_enabled: bool = False,
        habitat: HabitatState | None = None,
    ) -> None:
        self.state = state or PetRuntimeState()
        self.bus = bus or EventBus()
        self.life = life or LifeEngine()
        self.repository = repository
        self.habitat = habitat or HabitatState()
        self.habitat_controller = HabitatController(self.habitat)
        self.memory = MemoryManager(repository) if repository is not None else None
        self.memory_enabled = bool(memory_enabled)
        self.bus.subscribe(UserInteractionEvent, self._on_user_interaction)
        self.bus.subscribe(PlatformEvent, self._on_platform_event)

    @classmethod
    def from_database(cls, path: Path, *, enabled: bool = True) -> RuntimeController:
        if not enabled:
            return cls()
        repository = StateRepository(path)
        return cls(
            repository.load_state(),
            repository=repository,
            habitat=repository.load_habitat(),
        )

    def tick(self, dt: float, *, context: LifeContext | None = None) -> LifeDecision | None:
        return self.life.tick(self.state, dt, context=context)

    def publish(self, event: PetEvent) -> None:
        self.bus.publish(event)

    def sync_position(self, x: float, y: float, width: float, height: float) -> None:
        self.state.x = 0.0 if width <= 0 else min(1.0, max(0.0, x / width))
        self.state.y = 0.0 if height <= 0 else min(1.0, max(0.0, y / height))

    @property
    def persistence_enabled(self) -> bool:
        return self.repository is not None

    def conversation_history(self) -> tuple[tuple[str, str], ...]:
        return self.repository.recent_conversation() if self.repository else ()

    def append_conversation(self, role: str, text: str) -> None:
        if self.repository:
            self.repository.append_conversation(role, text)

    def remember_user_message(self, text: str) -> tuple[str, ...]:
        return self.memory.remember_from_user(text) if self.memory else ()

    def memory_context(self, query: str) -> str:
        return self.memory.prompt_context(query) if self.memory else ""

    def remember_shared_event(self, summary: str, *, salience: float = 0.65) -> str:
        return self.memory.remember_shared_event(summary, salience=salience) if self.memory else ""

    def save(self) -> None:
        if self.repository:
            self.repository.save_companion_state(self.state, self.habitat)

    def close(self) -> None:
        if self.repository:
            self.repository.save_companion_state(self.state, self.habitat)
            self.repository.close()
            self.repository = None

    def _on_user_interaction(self, event: UserInteractionEvent) -> None:
        previous_level = self.state.relationship_level
        activity = str(event.data.get("kind", event.name))
        self.life.interact(
            self.state,
            positive=event.name != "negative",
            activity=activity,
        )
        if (
            self.memory_enabled
            and self.memory is not None
            and self.state.relationship_level > previous_level
        ):
            self.memory.remember_relationship(
                f"Companion relationship reached level {self.state.relationship_level}"
            )
        self._record_meaningful_event(event, importance=0.7)

    def _on_platform_event(self, event: PlatformEvent) -> None:
        self._record_meaningful_event(event, importance=0.5)

    def _record_meaningful_event(self, event: PetEvent, *, importance: float) -> None:
        if self.repository is None:
            return
        private_keys = {
            "body",
            "context",
            "image",
            "message",
            "notification",
            "question",
            "text",
            "title",
        }
        safe_data = {
            key: value
            for key, value in event.data.items()
            if key.lower() not in private_keys and isinstance(value, (bool, float, int, str))
        }
        self.repository.record_event(
            event.name,
            {
                "event_id": event.event_id,
                "source": event.source.value,
                "priority": event.priority.value,
                "data": safe_data,
            },
            importance=importance,
        )
