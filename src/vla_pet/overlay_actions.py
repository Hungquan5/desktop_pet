from __future__ import annotations

import math

from vla_pet.contracts import ActionKind, PetAction
from vla_pet.world import PetWorld

NATIVE_SPRITE_FACING = {
    ActionKind.WALK: 1,
    ActionKind.THROW: 1,
}


def sprite_needs_flip(kind: ActionKind, desired_facing: int) -> bool:
    """Return whether a directional source image must be mirrored."""
    native = NATIVE_SPRITE_FACING.get(kind)
    if native is None:
        return False
    desired = -1 if desired_facing < 0 else 1
    return desired != native


class OverlayActionScheduler:
    """Turn raw VLA channels into varied, rate-limited desktop-pet behavior."""

    MIN_SPECIAL_GAP_S = 6.0
    JUMP_COOLDOWN_S = 12.0
    THROW_COOLDOWN_S = 20.0
    HAPPY_COOLDOWN_S = 15.0
    SAD_COOLDOWN_S = 20.0

    def __init__(self) -> None:
        self.last_special_at = -math.inf
        self.last_by_kind = {kind: -math.inf for kind in ActionKind}

    def choose(
        self,
        proposed: PetAction,
        world: PetWorld,
        now: float,
        *,
        edge_bounced: bool = False,
    ) -> PetAction:
        raw = tuple(proposed.raw_vector) + (0.0,) * max(0, 6 - len(proposed.raw_vector))
        is_discrete_policy = not proposed.raw_vector
        direction = proposed.direction if is_discrete_policy else (
            world.facing if abs(raw[0]) < 0.12 else proposed.direction
        )

        if now - self.last_special_at < self.MIN_SPECIAL_GAP_S:
            return self._walk(proposed, direction)

        if edge_bounced and self._ready(ActionKind.HAPPY, now, self.HAPPY_COOLDOWN_S):
            return self._special(ActionKind.HAPPY, proposed, direction, now, 1.0)

        pet_center = world.x + world.PET_WIDTH / 2
        near_center = abs(pet_center - world.WIDTH / 2) <= world.WIDTH * 0.10
        if is_discrete_policy:
            return self._choose_discrete(proposed, direction, near_center, now)

        if (
            raw[2] >= 1.20
            and near_center
            and self._ready(ActionKind.THROW, now, self.THROW_COOLDOWN_S)
        ):
            return self._special(ActionKind.THROW, proposed, direction, now, 0.9)

        if raw[1] >= 1.15 and self._ready(ActionKind.JUMP, now, self.JUMP_COOLDOWN_S):
            return self._special(ActionKind.JUMP, proposed, direction, now, 0.9)

        if raw[3] >= 0.30 and self._ready(ActionKind.HAPPY, now, self.HAPPY_COOLDOWN_S):
            return self._special(ActionKind.HAPPY, proposed, direction, now, 1.0)

        if raw[3] <= -0.45 and self._ready(ActionKind.SAD, now, self.SAD_COOLDOWN_S):
            return self._special(ActionKind.SAD, proposed, direction, now, 1.1)

        return self._walk(proposed, direction)

    def _choose_discrete(
        self,
        proposed: PetAction,
        direction: int,
        near_center: bool,
        now: float,
    ) -> PetAction:
        if proposed.kind is ActionKind.WALK:
            return self._walk(proposed, direction)
        if proposed.kind is ActionKind.IDLE:
            return PetAction(
                ActionKind.IDLE,
                direction=direction,
                duration=proposed.duration,
                source=proposed.source,
                note=proposed.note,
            )

        cooldowns = {
            ActionKind.JUMP: self.JUMP_COOLDOWN_S,
            ActionKind.THROW: self.THROW_COOLDOWN_S,
            ActionKind.HAPPY: self.HAPPY_COOLDOWN_S,
            ActionKind.SAD: self.SAD_COOLDOWN_S,
        }
        cooldown = cooldowns.get(proposed.kind)
        if cooldown is None or not self._ready(proposed.kind, now, cooldown):
            return self._walk(proposed, direction)
        if proposed.kind is ActionKind.THROW and not near_center:
            return self._walk(proposed, direction)
        durations = {
            ActionKind.JUMP: 0.9,
            ActionKind.THROW: 0.9,
            ActionKind.HAPPY: 1.0,
            ActionKind.SAD: 1.1,
        }
        return self._special(proposed.kind, proposed, direction, now, durations[proposed.kind])

    def _ready(self, kind: ActionKind, now: float, cooldown: float) -> bool:
        return now - self.last_by_kind[kind] >= cooldown

    def _walk(self, proposed: PetAction, direction: int) -> PetAction:
        return PetAction(
            ActionKind.WALK,
            direction=direction,
            speed=proposed.speed,
            duration=proposed.duration,
            source=proposed.source,
            raw_vector=proposed.raw_vector,
            note=proposed.note,
        )

    def _special(
        self,
        kind: ActionKind,
        proposed: PetAction,
        direction: int,
        now: float,
        duration: float,
    ) -> PetAction:
        self.last_special_at = now
        self.last_by_kind[kind] = now
        return PetAction(
            kind,
            direction=direction,
            speed=proposed.speed,
            duration=duration,
            source=proposed.source,
            raw_vector=proposed.raw_vector,
            note="; ".join(part for part in (proposed.note, f"overlay trigger: {kind.value}") if part),
        )
