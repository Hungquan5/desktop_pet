from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from typing import Any, TypeVar
from uuid import uuid4


class EventSource(str, Enum):
    USER = "user"
    PLATFORM = "platform"
    LIFE = "life"
    AI = "ai"
    SYSTEM = "system"


class EventPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class EventTrace:
    parent_event_id: str = ""
    span_id: str = field(default_factory=lambda: uuid4().hex)


@dataclass(frozen=True, slots=True)
class PetEvent:
    name: str
    source: EventSource
    data: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid4().hex)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    priority: EventPriority = EventPriority.NORMAL
    session_id: str = "local"
    idempotency_key: str = ""
    trace: EventTrace = field(default_factory=EventTrace)
    schema_version: str = field(default="pet.event/v1", init=False)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Event name cannot be empty")
        if not self.event_id or not self.session_id:
            raise ValueError("Event identity fields cannot be empty")
        if self.occurred_at.tzinfo is None:
            raise ValueError("Event timestamps must include a timezone")


@dataclass(frozen=True, slots=True)
class UserInteractionEvent(PetEvent):
    source: EventSource = field(default=EventSource.USER, init=False)


@dataclass(frozen=True, slots=True)
class PlatformEvent(PetEvent):
    source: EventSource = field(default=EventSource.PLATFORM, init=False)


@dataclass(frozen=True, slots=True)
class ConversationEvent(PetEvent):
    source: EventSource = field(default=EventSource.USER, init=False)


@dataclass(frozen=True, slots=True)
class AIEvent(PetEvent):
    source: EventSource = field(default=EventSource.AI, init=False)


@dataclass(frozen=True, slots=True)
class AnimationEvent(PetEvent):
    source: EventSource = field(default=EventSource.LIFE, init=False)


EventT = TypeVar("EventT", bound=PetEvent)
EventHandler = Callable[[PetEvent], None]


class EventBus:
    """Small synchronous bus for deterministic UI/life coordination."""

    def __init__(self, *, idempotency_window: int = 1024, max_queue: int = 512) -> None:
        self._handlers: dict[type[PetEvent], list[EventHandler]] = defaultdict(list)
        self._lock = RLock()
        self._idempotency_window = max(1, idempotency_window)
        self._seen_order: list[str] = []
        self._seen_keys: set[str] = set()
        self._max_queue = max(8, int(max_queue))
        self._queue: list[PetEvent] = []
        self._dispatching = False
        self._published = 0
        self._dropped = 0

    def subscribe(self, event_type: type[EventT], handler: Callable[[EventT], None]) -> Callable[[], None]:
        with self._lock:
            self._handlers[event_type].append(handler)  # type: ignore[arg-type]

        def unsubscribe() -> None:
            with self._lock:
                handlers = self._handlers.get(event_type, [])
                if handler in handlers:
                    handlers.remove(handler)  # type: ignore[arg-type]

        return unsubscribe

    def publish(self, event: PetEvent) -> bool:
        with self._lock:
            if event.idempotency_key:
                if event.idempotency_key in self._seen_keys:
                    return False
                self._seen_keys.add(event.idempotency_key)
                self._seen_order.append(event.idempotency_key)
                while len(self._seen_order) > self._idempotency_window:
                    self._seen_keys.discard(self._seen_order.pop(0))
            if len(self._queue) >= self._max_queue:
                if event.priority is EventPriority.LOW:
                    self._dropped += 1
                    return False
                low_index = next(
                    (
                        index
                        for index, queued in enumerate(self._queue)
                        if queued.priority is EventPriority.LOW
                    ),
                    None,
                )
                if low_index is None:
                    self._dropped += 1
                    return False
                self._queue.pop(low_index)
                self._dropped += 1
            self._queue.append(event)
            self._published += 1
            if self._dispatching:
                return True
            self._dispatching = True
        try:
            while True:
                with self._lock:
                    if not self._queue:
                        break
                    priorities = {
                        EventPriority.HIGH: 2,
                        EventPriority.NORMAL: 1,
                        EventPriority.LOW: 0,
                    }
                    selected = max(
                        range(len(self._queue)),
                        key=lambda index: (priorities[self._queue[index].priority], -index),
                    )
                    current = self._queue.pop(selected)
                    handlers = [
                        handler
                        for event_type, registered in self._handlers.items()
                        if isinstance(current, event_type)
                        for handler in tuple(registered)
                    ]
                for handler in handlers:
                    handler(current)
        finally:
            with self._lock:
                self._dispatching = False
        return True

    @property
    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "published": self._published,
                "dropped": self._dropped,
                "queued": len(self._queue),
            }
