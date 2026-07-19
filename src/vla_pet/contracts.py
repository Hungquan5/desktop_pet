from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np


class ActionKind(str, Enum):
    IDLE = "idle"
    WALK = "walk"
    JUMP = "jump"
    THROW = "throw"
    HAPPY = "happy"
    SAD = "sad"


class ActionIntent(str, Enum):
    """Structured language-layer request passed to the visual action policy."""

    WALK_LEFT = "WALK_LEFT"
    WALK_RIGHT = "WALK_RIGHT"
    JUMP = "JUMP"
    THROW = "THROW"
    HAPPY = "HAPPY"
    SAD = "SAD"
    IDLE = "IDLE"


@dataclass(frozen=True, slots=True)
class PetAction:
    kind: ActionKind
    direction: int = 1
    speed: float = 100.0
    duration: float = 1.0
    source: str = "unknown"
    raw_vector: tuple[float, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "direction", -1 if self.direction < 0 else 1)
        object.__setattr__(self, "speed", min(220.0, max(0.0, float(self.speed))))
        object.__setattr__(self, "duration", min(3.0, max(0.2, float(self.duration))))

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "direction": self.direction,
            "speed": round(self.speed, 3),
            "duration": round(self.duration, 3),
            "source": self.source,
            "raw_vector": [round(value, 5) for value in self.raw_vector],
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class ActionEvent:
    sequence_id: int
    requested: ActionKind
    executed: ActionKind
    result: str
    nearby_object: str | None
    elapsed: float
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence_id": self.sequence_id,
            "requested": self.requested.value,
            "executed": self.executed.value,
            "result": self.result,
            "nearby_object": self.nearby_object,
            "elapsed": round(self.elapsed, 3),
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class SandboxObservation:
    sequence_id: int
    images: dict[str, np.ndarray]
    state: tuple[float, float, float, float, float, float]
    task: str
    requested_action: ActionIntent | None = None

    def validate(self) -> None:
        allowed = {"observation.image", "observation.image2", "observation.image3"}
        keys = set(self.images)
        if "observation.image" not in keys or keys - allowed:
            raise ValueError(
                "Images must contain observation.image and may contain observation.image2/image3"
            )
        for key, image in self.images.items():
            if image.shape != (3, 256, 256):
                raise ValueError(f"{key} has shape {image.shape}; expected (3, 256, 256)")
            if image.dtype != np.float32:
                raise ValueError(f"{key} must use float32, got {image.dtype}")
            if not np.isfinite(image).all():
                raise ValueError(f"{key} contains non-finite values")
        if len(self.state) != 6 or not np.isfinite(self.state).all():
            raise ValueError("State must contain six finite values")
        if self.requested_action is not None and not isinstance(self.requested_action, ActionIntent):
            raise ValueError("Requested action must be an ActionIntent")


@dataclass(frozen=True, slots=True)
class VisualQuestion:
    """A user-authorized desktop screenshot and a question about it."""

    image: np.ndarray
    question: str
    notification_context: str = ""

    def validate(self) -> None:
        if self.image.ndim != 3 or self.image.shape[2] != 3:
            raise ValueError(f"Screenshot has shape {self.image.shape}; expected HxWx3")
        if self.image.dtype != np.uint8:
            raise ValueError(f"Screenshot must use uint8, got {self.image.dtype}")
        if not self.question.strip():
            raise ValueError("Question cannot be empty")
        if len(self.question) > 500:
            raise ValueError("Question is too long")
        if len(self.notification_context) > 1000:
            raise ValueError("Notification context is too long")


@dataclass(frozen=True, slots=True)
class NotificationRequest:
    """Opted-in notification text used ephemerally by the language layer."""

    context: str

    def validate(self) -> None:
        if not self.context.strip() or len(self.context) > 1000:
            raise ValueError("Invalid notification context")


@dataclass(frozen=True, slots=True)
class AudioTranscription:
    """Ephemeral mono PCM/WAV request; bytes are never persisted or logged."""

    wave_bytes: bytes
    language: str = ""

    def validate(self) -> None:
        if not self.wave_bytes.startswith(b"RIFF") or b"WAVE" not in self.wave_bytes[:16]:
            raise ValueError("Audio transcription expects WAV bytes")
        if not 44 <= len(self.wave_bytes) <= 5 * 1024 * 1024:
            raise ValueError("Audio transcription exceeds the supported size")
        if len(self.language) > 16:
            raise ValueError("Audio language hint is invalid")


@dataclass(frozen=True, slots=True)
class ChatRequest:
    message: str
    history: tuple[tuple[str, str], ...] = ()
    memory_context: str = ""

    def validate(self) -> None:
        if not self.message.strip():
            raise ValueError("Chat message cannot be empty")
        if len(self.message) > 500:
            raise ValueError("Chat message is too long")
        if len(self.history) > 12:
            raise ValueError("Chat history is too long")
        if len(self.memory_context) > 1500:
            raise ValueError("Chat memory context is too long")
        for role, text in self.history:
            if role not in {"user", "pet"} or not text or len(text) > 500:
                raise ValueError("Invalid chat history entry")


@dataclass(frozen=True, slots=True)
class ChatResult:
    """One SmolLM turn: visible dialogue plus an optional physical intent."""

    reply: str
    requested_action: ActionIntent | None = None

    def validate(self) -> None:
        if not self.reply.strip() or len(self.reply) > 500:
            raise ValueError("Invalid chat reply")
        if self.requested_action is not None and not isinstance(self.requested_action, ActionIntent):
            raise ValueError("Invalid chat action intent")


@dataclass(frozen=True, slots=True)
class LanguageNarration:
    """Image-free action event for the SmolLM language layer."""

    event: ActionEvent

    def validate(self) -> None:
        if not isinstance(self.event, ActionEvent):
            raise ValueError("Narration event is invalid")

@dataclass(frozen=True, slots=True)
class WorkerRequest:
    request_id: int
    kind: str
    payload: Any


@dataclass(frozen=True, slots=True)
class WorkerResponse:
    request_id: int
    kind: str
    ok: bool
    payload: Any
    provider: str
    latency_s: float
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
