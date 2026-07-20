from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

import numpy as np

from vla_pet.contracts import HabitatIntent


class HabitatObjectKind(str, Enum):
    CUSHION = "cushion"
    SNACK = "snack"
    BALL = "ball"
    BOX = "box"


class HabitatObjectStatus(str, Enum):
    PLACED = "placed"
    DRAGGING = "dragging"
    AIRBORNE = "airborne"
    RESERVED = "reserved"
    CONSUMED = "consumed"
    OCCUPIED = "occupied"


@dataclass(slots=True)
class HabitatObjectState:
    object_id: str
    kind: HabitatObjectKind
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    status: HabitatObjectStatus = HabitatObjectStatus.PLACED
    visible: bool = True

    def normalize(self, *, restore: bool = False) -> None:
        self.object_id = str(self.object_id).strip()[:80]
        self.kind = HabitatObjectKind(self.kind)
        self.x = min(1.0, max(0.0, float(self.x)))
        self.y = min(1.0, max(0.0, float(self.y)))
        self.vx = min(900.0, max(-900.0, float(self.vx)))
        self.vy = min(900.0, max(-900.0, float(self.vy)))
        self.status = HabitatObjectStatus(self.status)
        self.visible = bool(self.visible)
        if restore:
            self.vx = self.vy = 0.0
            if self.status in {HabitatObjectStatus.DRAGGING, HabitatObjectStatus.AIRBORNE}:
                self.status = HabitatObjectStatus.PLACED

    def snapshot(self) -> dict[str, Any]:
        value = asdict(self)
        value["kind"] = self.kind.value
        value["status"] = self.status.value
        return value

    @classmethod
    def from_snapshot(cls, value: Any) -> HabitatObjectState | None:
        if not isinstance(value, dict):
            return None
        try:
            item = cls(
                object_id=str(value.get("object_id", "")),
                kind=HabitatObjectKind(str(value.get("kind", ""))),
                x=float(value.get("x", 0.5)),
                y=float(value.get("y", 0.75)),
                vx=float(value.get("vx", 0.0)),
                vy=float(value.get("vy", 0.0)),
                status=HabitatObjectStatus(str(value.get("status", "placed"))),
                visible=bool(value.get("visible", True)),
            )
            item.normalize(restore=True)
            return item if item.object_id else None
        except (TypeError, ValueError):
            return None


def _default_objects() -> list[HabitatObjectState]:
    return [
        HabitatObjectState("cushion", HabitatObjectKind.CUSHION, 0.18, 0.78),
        HabitatObjectState("ball", HabitatObjectKind.BALL, 0.57, 0.70),
        HabitatObjectState("box", HabitatObjectKind.BOX, 0.82, 0.73),
    ]


@dataclass(slots=True)
class HabitatState:
    schema_version: int = 1
    enabled: bool = True
    collapsed: bool = False
    anchor_x: float = 0.98
    objects: list[HabitatObjectState] = field(default_factory=_default_objects)
    active_intent: HabitatIntent = HabitatIntent.NONE
    active_object_id: str = ""
    interaction_started_at: float = 0.0
    reward_timestamps: dict[str, float] = field(default_factory=dict)
    completed_tokens: list[str] = field(default_factory=list)

    def normalize(self, *, restore: bool = False) -> None:
        self.schema_version = 1
        self.enabled = bool(self.enabled)
        self.collapsed = bool(self.collapsed)
        self.anchor_x = min(1.0, max(0.0, float(self.anchor_x)))
        unique: dict[str, HabitatObjectState] = {}
        for item in self.objects:
            item.normalize(restore=restore)
            if item.object_id and item.status is not HabitatObjectStatus.CONSUMED:
                unique[item.object_id] = item
        self.objects = list(unique.values())
        self.active_intent = HabitatIntent(self.active_intent)
        self.active_object_id = str(self.active_object_id).strip()[:80]
        self.interaction_started_at = max(0.0, float(self.interaction_started_at))
        self.reward_timestamps = {
            str(key)[:80]: max(0.0, float(value))
            for key, value in self.reward_timestamps.items()
        }
        self.completed_tokens = list(dict.fromkeys(str(item)[:120] for item in self.completed_tokens))[
            -128:
        ]
        if restore:
            self.active_intent = HabitatIntent.NONE
            self.active_object_id = ""
            self.interaction_started_at = 0.0

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "enabled": self.enabled,
            "collapsed": self.collapsed,
            "anchor_x": round(self.anchor_x, 6),
            "objects": [item.snapshot() for item in self.objects],
            "active_intent": self.active_intent.value,
            "active_object_id": self.active_object_id,
            "interaction_started_at": self.interaction_started_at,
            "reward_timestamps": dict(self.reward_timestamps),
            "completed_tokens": list(self.completed_tokens),
        }

    @classmethod
    def from_snapshot(cls, value: Any) -> HabitatState:
        if not isinstance(value, dict) or int(value.get("schema_version", 0)) != 1:
            return cls()
        objects = [
            item
            for raw in value.get("objects", [])
            if (item := HabitatObjectState.from_snapshot(raw)) is not None
        ]
        try:
            state = cls(
                enabled=bool(value.get("enabled", True)),
                collapsed=bool(value.get("collapsed", False)),
                anchor_x=float(value.get("anchor_x", 0.98)),
                objects=objects or _default_objects(),
                active_intent=HabitatIntent(str(value.get("active_intent", "none"))),
                active_object_id=str(value.get("active_object_id", "")),
                interaction_started_at=float(value.get("interaction_started_at", 0.0)),
                reward_timestamps=dict(value.get("reward_timestamps", {})),
                completed_tokens=list(value.get("completed_tokens", [])),
            )
            state.normalize(restore=True)
            return state
        except (TypeError, ValueError):
            return cls()


@dataclass(frozen=True, slots=True)
class EnvironmentSnapshot:
    pet_x: float
    pet_y: float
    energy: float
    boredom: float
    curiosity: float
    objects: tuple[tuple[str, str, float, float, str], ...]
    candidates: tuple[HabitatIntent, ...]

    def validate(self) -> None:
        for value in (self.pet_x, self.pet_y, self.energy, self.boredom, self.curiosity):
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError("Environment snapshot values must be normalized")
        if not self.candidates or any(not isinstance(item, HabitatIntent) for item in self.candidates):
            raise ValueError("Environment snapshot must have typed candidate intents")


@dataclass(frozen=True, slots=True)
class HabitatObservation:
    """A pet-owned synthetic scene; it never contains desktop capture pixels."""

    sequence_id: int
    image: np.ndarray
    environment: EnvironmentSnapshot

    def validate(self) -> None:
        if self.image.shape != (3, 256, 256) or self.image.dtype != np.float32:
            raise ValueError("Habitat image must be float32 CHW 256x256")
        if not np.isfinite(self.image).all() or not 0.0 <= float(self.image.min()) <= float(
            self.image.max()
        ) <= 1.0:
            raise ValueError("Habitat image values must be finite and normalized")
        self.environment.validate()


@dataclass(frozen=True, slots=True)
class HabitatCompletion:
    accepted: bool
    reward_allowed: bool
    object_id: str
    intent: HabitatIntent


class HabitatController:
    """Pure deterministic habitat behavior; Qt owns only rendering and pointer input."""

    WIDTH = 420.0
    HEIGHT = 190.0
    FLOOR_Y = 156.0
    BALL_RADIUS = 14.0
    GRAVITY = 760.0
    REWARD_COOLDOWN_S = 60.0

    def __init__(self, state: HabitatState | None = None) -> None:
        self.state = state or HabitatState()
        self.state.normalize()

    def object(self, object_id: str) -> HabitatObjectState | None:
        return next((item for item in self.state.objects if item.object_id == object_id), None)

    def candidates(self, *, snack_count: int = 0) -> tuple[HabitatIntent, ...]:
        choices = [HabitatIntent.RETURN_HOME, HabitatIntent.REST]
        if snack_count > 0 or self.object("snack") is not None:
            choices.append(HabitatIntent.EAT_SNACK)
        if self.object("ball") is not None:
            choices.extend((HabitatIntent.CHASE_BALL, HabitatIntent.FETCH_BALL))
        choices.append(
            HabitatIntent.EXIT_BOX
            if self.state.active_intent is HabitatIntent.ENTER_BOX
            else HabitatIntent.ENTER_BOX
        )
        return tuple(choices)

    def environment_snapshot(
        self,
        *,
        pet_x: float,
        pet_y: float,
        energy: float,
        boredom: float,
        curiosity: float,
        snack_count: int,
    ) -> EnvironmentSnapshot:
        snapshot = EnvironmentSnapshot(
            pet_x=min(1.0, max(0.0, pet_x)),
            pet_y=min(1.0, max(0.0, pet_y)),
            energy=min(1.0, max(0.0, energy)),
            boredom=min(1.0, max(0.0, boredom)),
            curiosity=min(1.0, max(0.0, curiosity)),
            objects=tuple(
                (item.object_id, item.kind.value, item.x, item.y, item.status.value)
                for item in self.state.objects
                if item.visible
            ),
            candidates=self.candidates(snack_count=snack_count),
        )
        snapshot.validate()
        return snapshot

    def choose_deterministic_intent(
        self, *, energy: float, boredom: float, curiosity: float, snack_count: int
    ) -> HabitatIntent:
        if energy < 0.28:
            return HabitatIntent.REST
        if snack_count > 0 and energy < 0.55:
            return HabitatIntent.EAT_SNACK
        if boredom > 0.62 and self.object("ball") is not None:
            return HabitatIntent.CHASE_BALL
        if curiosity > 0.72:
            return HabitatIntent.ENTER_BOX
        return HabitatIntent.RETURN_HOME

    def set_collapsed(self, collapsed: bool) -> None:
        self.state.collapsed = bool(collapsed)
        for item in self.state.objects:
            item.vx = item.vy = 0.0
            item.x = min(1.0, max(0.0, item.x))
            item.y = min(1.0, max(0.0, item.y))
            if item.status in {HabitatObjectStatus.DRAGGING, HabitatObjectStatus.AIRBORNE}:
                item.status = HabitatObjectStatus.PLACED

    def spawn_snack(self, available: int, *, x: float = 0.48, y: float = 0.42) -> bool:
        if available <= 0 or self.object("snack") is not None:
            return False
        self.state.objects.append(
            HabitatObjectState("snack", HabitatObjectKind.SNACK, x, y, status=HabitatObjectStatus.RESERVED)
        )
        return True

    def remove_unconsumed_snack(self) -> bool:
        snack = self.object("snack")
        if snack is None or snack.status is HabitatObjectStatus.CONSUMED:
            return False
        self.state.objects.remove(snack)
        return True

    def consume_snack(self) -> bool:
        snack = self.object("snack")
        if snack is None or snack.status is HabitatObjectStatus.CONSUMED:
            return False
        snack.status = HabitatObjectStatus.CONSUMED
        snack.visible = False
        self.state.objects.remove(snack)
        return True

    def start_drag(self, object_id: str) -> bool:
        item = self.object(object_id)
        if item is None or not item.visible:
            return False
        item.status = HabitatObjectStatus.DRAGGING
        item.vx = item.vy = 0.0
        return True

    def drag_to(self, object_id: str, x: float, y: float) -> bool:
        item = self.object(object_id)
        if item is None or item.status is not HabitatObjectStatus.DRAGGING:
            return False
        item.x = min(1.0, max(0.0, float(x)))
        item.y = min(0.88, max(0.08, float(y)))
        return True

    def release_drag(self, object_id: str, vx: float = 0.0, vy: float = 0.0) -> bool:
        item = self.object(object_id)
        if item is None or item.status is not HabitatObjectStatus.DRAGGING:
            return False
        if item.kind is HabitatObjectKind.BALL:
            item.vx = min(620.0, max(-620.0, float(vx)))
            item.vy = min(480.0, max(-480.0, float(vy)))
            item.status = HabitatObjectStatus.AIRBORNE
        else:
            item.vx = item.vy = 0.0
            item.y = min(item.y, 0.82 if item.kind is HabitatObjectKind.CUSHION else 0.78)
            item.status = (
                HabitatObjectStatus.RESERVED
                if item.kind is HabitatObjectKind.SNACK
                else HabitatObjectStatus.PLACED
            )
        return True

    def begin_interaction(self, intent: HabitatIntent, object_id: str, now: float) -> bool:
        if intent not in self.candidates(snack_count=1) and intent is not HabitatIntent.CANCEL:
            return False
        if object_id and self.object(object_id) is None:
            return False
        self.state.active_intent = intent
        self.state.active_object_id = object_id
        self.state.interaction_started_at = max(0.0, float(now))
        return True

    def complete_interaction(
        self, *, token: str, object_id: str, now: float
    ) -> HabitatCompletion:
        intent = self.state.active_intent
        if not token or token in self.state.completed_tokens:
            return HabitatCompletion(False, False, object_id, intent)
        if object_id != self.state.active_object_id:
            return HabitatCompletion(False, False, object_id, intent)
        self.state.completed_tokens.append(token[:120])
        self.state.completed_tokens = self.state.completed_tokens[-128:]
        last = self.state.reward_timestamps.get(object_id, -self.REWARD_COOLDOWN_S)
        reward = float(now) - last >= self.REWARD_COOLDOWN_S
        if reward:
            self.state.reward_timestamps[object_id] = float(now)
        self.state.active_intent = HabitatIntent.NONE
        self.state.active_object_id = ""
        self.state.interaction_started_at = 0.0
        return HabitatCompletion(True, reward, object_id, intent)

    def update(self, dt: float) -> bool:
        if not self.state.enabled or self.state.collapsed:
            return False
        dt = min(0.05, max(0.0, float(dt)))
        changed = False
        for item in self.state.objects:
            if item.kind is not HabitatObjectKind.BALL or item.status is not HabitatObjectStatus.AIRBORNE:
                continue
            item.vy += self.GRAVITY * dt
            item.x += item.vx * dt / self.WIDTH
            item.y += item.vy * dt / self.HEIGHT
            item.vx *= 0.992
            radius_x = self.BALL_RADIUS / self.WIDTH
            floor_y = (self.FLOOR_Y - self.BALL_RADIUS) / self.HEIGHT
            if item.x < radius_x or item.x > 1.0 - radius_x:
                item.x = min(1.0 - radius_x, max(radius_x, item.x))
                item.vx = -item.vx * 0.62
            if item.y >= floor_y:
                item.y = floor_y
                if abs(item.vy) > 42.0:
                    item.vy = -abs(item.vy) * 0.42
                else:
                    item.vy = 0.0
                    item.vx *= 0.86
                if abs(item.vx) < 8.0 and abs(item.vy) < 8.0:
                    item.vx = item.vy = 0.0
                    item.status = HabitatObjectStatus.PLACED
            changed = True
        return changed
