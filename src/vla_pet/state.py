from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _bounded(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(high, max(low, float(value)))


@dataclass(slots=True)
class NeedState:
    energy: float = 0.82
    boredom: float = 0.18
    social: float = 0.72
    curiosity: float = 0.55

    def clamp(self) -> None:
        self.energy = _bounded(self.energy)
        self.boredom = _bounded(self.boredom)
        self.social = _bounded(self.social)
        self.curiosity = _bounded(self.curiosity)


@dataclass(slots=True)
class EmotionState:
    valence: float = 0.25
    arousal: float = 0.35
    affection: float = 0.10
    tag: str = "content"

    def clamp(self) -> None:
        self.valence = _bounded(self.valence, -1.0, 1.0)
        self.arousal = _bounded(self.arousal, -1.0, 1.0)
        self.affection = _bounded(self.affection)


@dataclass(slots=True)
class ProgressionState:
    """Positive-only progression; absence never penalizes the user."""

    xp: int = 0
    level: int = 1
    affection_points: int = 0
    focus_minutes: int = 0
    play_count: int = 0
    daily_streak: int = 0
    last_daily_date: str = ""
    inventory: dict[str, int] = field(default_factory=lambda: {"snack": 2, "ball": 1})
    achievements: list[str] = field(default_factory=list)

    def normalize(self) -> None:
        self.xp = max(0, int(self.xp))
        self.level = max(1, int(self.level))
        self.affection_points = max(0, int(self.affection_points))
        self.focus_minutes = max(0, int(self.focus_minutes))
        self.play_count = max(0, int(self.play_count))
        self.daily_streak = max(0, int(self.daily_streak))
        self.inventory = {
            str(name): max(0, int(count))
            for name, count in self.inventory.items()
            if str(name).strip() and int(count) > 0
        }
        self.achievements = list(dict.fromkeys(str(item) for item in self.achievements if item))


@dataclass(slots=True)
class PetRuntimeState:
    schema_version: int = 2
    x: float = 0.35
    y: float = 1.0
    current_animation: str = "idle"
    active_intention: str = "rest"
    speaking: bool = False
    listening: bool = False
    audio_state: str = "idle"
    current_task: str = ""
    privacy_mode: bool = False
    needs: NeedState = field(default_factory=NeedState)
    emotion: EmotionState = field(default_factory=EmotionState)
    progression: ProgressionState = field(default_factory=ProgressionState)
    relationship_level: int = 0
    interaction_count: int = 0
    last_interaction_at: float = 0.0
    last_life_tick_at: float = 0.0

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> PetRuntimeState:
        version = int(data.get("schema_version", 0))
        if version not in {1, 2}:
            return cls()
        needs = NeedState(**data.get("needs", {}))
        emotion = EmotionState(**data.get("emotion", {}))
        progression = ProgressionState(**data.get("progression", {}))
        state = cls(
            **{
                key: value
                for key, value in data.items()
                if key not in {"needs", "emotion", "progression", "schema_version"}
                and key in cls.__dataclass_fields__
            },
            needs=needs,
            emotion=emotion,
            progression=progression,
        )
        needs.clamp()
        emotion.clamp()
        progression.normalize()
        return state
