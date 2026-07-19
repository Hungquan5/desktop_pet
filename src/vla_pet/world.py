from __future__ import annotations

from dataclasses import dataclass

from vla_pet.contracts import ActionEvent, ActionKind, PetAction


@dataclass(slots=True)
class ToyState:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    radius: float = 16.0


class PetWorld:
    WIDTH = 960
    HEIGHT = 540
    FLOOR_Y = 466.0
    PET_WIDTH = 112.0
    PET_HEIGHT = 124.0
    GRAVITY = 720.0
    DROP_GRAVITY = 260.0
    DROP_MAX_SPEED = 280.0

    def __init__(
        self,
        *,
        width: int | None = None,
        height: int | None = None,
        floor_y: float | None = None,
        bounce_edges: bool = False,
        environment_label: str = "room",
        require_throw_target: bool = True,
    ) -> None:
        if width is not None:
            self.WIDTH = width
        if height is not None:
            self.HEIGHT = height
        if floor_y is not None:
            self.FLOOR_Y = floor_y
        self.bounce_edges = bounce_edges
        self.environment_label = environment_label
        self.require_throw_target = require_throw_target
        self.sequence_id = 0
        self.reset()

    def reset(self) -> None:
        self.x = self.WIDTH * 0.35
        self.y = self.FLOOR_Y - self.PET_HEIGHT
        self.vx = 0.0
        self.vy = 0.0
        self.on_ground = True
        self.being_held = False
        self.user_falling = False
        self.holding = False
        self.facing = 1
        self.toy = ToyState(self.WIDTH * 0.68, self.FLOOR_Y - 16.0)
        self.active_action: PetAction | None = None
        self.executed_kind = ActionKind.IDLE
        self.action_elapsed = 0.0
        self.action_remaining = 0.0
        self.action_result = ""
        self.sequence_id += 1

    @property
    def is_busy(self) -> bool:
        return self.active_action is not None

    @property
    def pose(self) -> ActionKind:
        if not self.on_ground:
            return ActionKind.JUMP
        return self.executed_kind if self.active_action else ActionKind.IDLE

    def nearby_object(self) -> str | None:
        pet_center = self.x + self.PET_WIDTH / 2
        return "toy" if abs(pet_center - self.toy.x) <= 130 else None

    def normalized_state(self) -> tuple[float, float, float, float, float, float]:
        return (
            max(-1.0, min(1.0, (self.x / (self.WIDTH - self.PET_WIDTH)) * 2.0 - 1.0)),
            max(-1.0, min(1.0, (self.y / (self.FLOOR_Y - self.PET_HEIGHT)) * 2.0 - 1.0)),
            max(-1.0, min(1.0, self.vx / 220.0)),
            max(-1.0, min(1.0, self.vy / 500.0)),
            1.0 if self.on_ground else -1.0,
            1.0 if self.holding else -1.0,
        )

    def apply_action(self, action: PetAction) -> None:
        if self.is_busy:
            raise RuntimeError("Cannot start a new action while another action is active")

        self.sequence_id += 1
        self.active_action = action
        self.executed_kind = action.kind
        self.action_elapsed = 0.0
        self.action_remaining = action.duration
        self.facing = action.direction
        self.action_result = f"completed {action.kind.value}"

        if action.kind is ActionKind.WALK:
            self.vx = action.direction * action.speed
            self.action_result = f"walked across the {self.environment_label}"
        elif action.kind is ActionKind.JUMP:
            if self.on_ground:
                self.vy = -max(300.0, action.speed * 2.0)
                self.on_ground = False
                self.action_result = "jumped and landed safely"
            else:
                self._replace_with_idle("could not jump while airborne")
        elif action.kind is ActionKind.THROW:
            if not self.require_throw_target:
                self.action_result = "performed a playful throw"
            elif self.nearby_object() == "toy":
                self.toy.x = self.x + self.PET_WIDTH / 2 + action.direction * 25
                self.toy.y = self.y + self.PET_HEIGHT * 0.45
                self.toy.vx = action.direction * 320.0
                self.toy.vy = -210.0
                self.action_result = "threw the toy across the room"
            else:
                self._replace_with_idle("could not reach the toy")
        elif action.kind is ActionKind.HAPPY:
            self.action_result = "did a happy bounce"
        elif action.kind is ActionKind.SAD:
            self.action_result = "paused with a sad expression"
        else:
            self.action_result = f"looked around the {self.environment_label}"

    def interrupt(self) -> None:
        """Safely cancel motion when the user grabs or pets the character."""
        self.active_action = None
        self.executed_kind = ActionKind.IDLE
        self.action_remaining = 0.0
        self.vx = 0.0
        if self.on_ground:
            self.vy = 0.0
        self.sequence_id += 1

    def move_horizontal(self, x: float) -> None:
        self.x = max(0.0, min(self.WIDTH - self.PET_WIDTH, float(x)))

    def pick_up(self) -> None:
        self.interrupt()
        self.being_held = True
        self.user_falling = False
        self.on_ground = False
        self.vx = 0.0
        self.vy = 0.0

    def move_to(self, x: float, y: float) -> None:
        self.move_horizontal(x)
        ground_y = self.FLOOR_Y - self.PET_HEIGHT
        self.y = max(0.0, min(ground_y, float(y)))
        self.on_ground = self.y >= ground_y
        self.vx = 0.0
        self.vy = 0.0

    def drop(self) -> None:
        self.being_held = False
        ground_y = self.FLOOR_Y - self.PET_HEIGHT
        if self.y >= ground_y:
            self.y = ground_y
            self.on_ground = True
            self.user_falling = False
        else:
            self.on_ground = False
            self.user_falling = True
            self.vy = 0.0
        self.sequence_id += 1

    def _replace_with_idle(self, result: str) -> None:
        assert self.active_action is not None
        requested = self.active_action
        self.executed_kind = ActionKind.IDLE
        self.active_action = PetAction(
            ActionKind.IDLE,
            direction=requested.direction,
            duration=min(requested.duration, 0.7),
            source=requested.source,
            raw_vector=requested.raw_vector,
            note=result,
        )
        self.action_remaining = self.active_action.duration
        self.action_result = result

    def update(self, dt: float) -> ActionEvent | None:
        dt = min(max(dt, 0.0), 0.1)
        if self.active_action:
            self.action_elapsed += dt
            self.action_remaining -= dt

        if not self.being_held:
            if not self.on_ground:
                if self.user_falling:
                    self.vy = min(self.DROP_MAX_SPEED, self.vy + self.DROP_GRAVITY * dt)
                else:
                    self.vy += self.GRAVITY * dt
            self.x += self.vx * dt
            self.y += self.vy * dt

        max_x = self.WIDTH - self.PET_WIDTH
        if self.x <= 0:
            self.x = 0
            if self.bounce_edges and self.vx < 0:
                self.vx = abs(self.vx)
                self.facing = 1
            else:
                self.vx = max(0.0, self.vx)
        elif self.x >= max_x:
            self.x = max_x
            if self.bounce_edges and self.vx > 0:
                self.vx = -abs(self.vx)
                self.facing = -1
            else:
                self.vx = min(0.0, self.vx)

        ground_y = self.FLOOR_Y - self.PET_HEIGHT
        if self.y >= ground_y:
            self.y = ground_y
            self.vy = 0.0
            self.on_ground = True
            self.user_falling = False

        self._update_toy(dt)

        if not self.active_action:
            return None
        jump_still_airborne = self.executed_kind is ActionKind.JUMP and not self.on_ground
        if self.action_remaining > 0 or jump_still_airborne:
            return None

        action = self.active_action
        event = ActionEvent(
            sequence_id=self.sequence_id,
            requested=action.kind if not action.note else self._requested_from_note(action),
            executed=self.executed_kind,
            result=self.action_result,
            nearby_object=self.nearby_object(),
            elapsed=self.action_elapsed,
            source=action.source,
        )
        self.active_action = None
        self.executed_kind = ActionKind.IDLE
        self.action_remaining = 0.0
        self.vx = 0.0
        return event

    @staticmethod
    def _requested_from_note(action: PetAction) -> ActionKind:
        # Invalid actions are replaced with idle, but their note retains the reason.
        if "jump" in action.note:
            return ActionKind.JUMP
        if "toy" in action.note:
            return ActionKind.THROW
        return action.kind

    def _update_toy(self, dt: float) -> None:
        airborne = self.toy.y < self.FLOOR_Y - self.toy.radius or abs(self.toy.vy) > 1
        if airborne:
            self.toy.vy += self.GRAVITY * dt
            self.toy.x += self.toy.vx * dt
            self.toy.y += self.toy.vy * dt
            self.toy.vx *= 0.995

        if self.toy.x < self.toy.radius:
            self.toy.x = self.toy.radius
            self.toy.vx = abs(self.toy.vx) * 0.65
        elif self.toy.x > self.WIDTH - self.toy.radius:
            self.toy.x = self.WIDTH - self.toy.radius
            self.toy.vx = -abs(self.toy.vx) * 0.65

        floor = self.FLOOR_Y - self.toy.radius
        if self.toy.y >= floor:
            self.toy.y = floor
            if abs(self.toy.vy) > 45:
                self.toy.vy = -abs(self.toy.vy) * 0.45
            else:
                self.toy.vy = 0.0
                self.toy.vx *= 0.92
