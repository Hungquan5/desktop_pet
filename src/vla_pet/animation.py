from __future__ import annotations

from dataclasses import dataclass

from vla_pet.character import AnimationSpec, CharacterPack
from vla_pet.contracts import ActionKind


@dataclass(slots=True)
class AnimationController:
    pack: CharacterPack
    current: ActionKind = ActionKind.IDLE
    started_at: float = 0.0
    current_role: str = "idle"

    def select(self, kind: ActionKind, now: float, *, force: bool = False) -> bool:
        if kind is self.current and self.current_role == kind.value:
            return True
        current_spec = self.pack.animation_for(self.current_role)
        next_spec = self.pack.animation_for(kind)
        if not force and next_spec.priority < current_spec.priority and not self.finished(now):
            return False
        self.current = kind
        self.current_role = kind.value
        self.started_at = now
        return True

    def select_role(self, role: str, now: float, *, force: bool = False) -> bool:
        name = str(role).strip().lower() or "idle"
        if name == self.current_role:
            return True
        current_spec = self.pack.animation_for(self.current_role)
        next_spec = self.pack.animation_for(name)
        if not force and next_spec.priority < current_spec.priority and not self.finished(now):
            return False
        self.current_role = name
        try:
            self.current = ActionKind(name)
        except ValueError:
            self.current = CharacterPack._ROLE_FALLBACKS.get(name, ActionKind.IDLE)
        self.started_at = now
        return True

    def frame(self, now: float, kind: ActionKind | None = None) -> str:
        if kind is not None and kind is not self.current:
            self.select(kind, now, force=kind is ActionKind.IDLE)
        spec = self.pack.animation_for(self.current_role)
        return str(spec.frames[self._frame_index(spec, now)])

    def frame_role(self, now: float, role: str | None = None) -> str:
        if role is not None and role != self.current_role:
            self.select_role(role, now, force=role == "idle")
        spec = self.pack.animation_for(self.current_role)
        return str(spec.frames[self._frame_index(spec, now)])

    def finished(self, now: float) -> bool:
        spec = self.pack.animation_for(self.current_role)
        return not spec.loop and max(0.0, now - self.started_at) * spec.fps >= len(spec.frames)

    def _frame_index(self, spec: AnimationSpec, now: float) -> int:
        elapsed_frames = int(max(0.0, now - self.started_at) * spec.fps)
        if spec.loop:
            return elapsed_frames % len(spec.frames)
        return min(len(spec.frames) - 1, elapsed_frames)
