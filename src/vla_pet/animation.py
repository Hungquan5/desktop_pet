from __future__ import annotations

from dataclasses import dataclass

from vla_pet.character import AnimationSpec, CharacterPack
from vla_pet.contracts import ActionKind


@dataclass(slots=True)
class AnimationController:
    pack: CharacterPack
    current: ActionKind = ActionKind.IDLE
    started_at: float = 0.0

    def select(self, kind: ActionKind, now: float, *, force: bool = False) -> bool:
        if kind is self.current:
            return True
        current_spec = self.pack.animations[self.current]
        next_spec = self.pack.animations[kind]
        if not force and next_spec.priority < current_spec.priority and not self.finished(now):
            return False
        self.current = kind
        self.started_at = now
        return True

    def frame(self, now: float, kind: ActionKind | None = None) -> str:
        if kind is not None and kind is not self.current:
            self.select(kind, now, force=kind is ActionKind.IDLE)
        spec = self.pack.animations[self.current]
        return str(spec.frames[self._frame_index(spec, now)])

    def finished(self, now: float) -> bool:
        spec = self.pack.animations[self.current]
        return not spec.loop and max(0.0, now - self.started_at) * spec.fps >= len(spec.frames)

    def _frame_index(self, spec: AnimationSpec, now: float) -> int:
        elapsed_frames = int(max(0.0, now - self.started_at) * spec.fps)
        if spec.loop:
            return elapsed_frames % len(spec.frames)
        return min(len(spec.frames) - 1, elapsed_frames)
