from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from vla_pet.state import PetRuntimeState


@dataclass(frozen=True, slots=True)
class ProgressionResult:
    xp_awarded: int
    level_before: int
    level_after: int
    unlocked: tuple[str, ...] = ()


class ProgressionEngine:
    """Deterministic, non-punishing rewards for interaction and focus."""

    LEVEL_STEP = 100

    def award(self, state: PetRuntimeState, xp: int, *, reason: str = "") -> ProgressionResult:
        progress = state.progression
        before = progress.level
        amount = max(0, int(xp))
        progress.xp += amount
        progress.level = 1 + progress.xp // self.LEVEL_STEP
        unlocked: list[str] = []
        if progress.level >= 2:
            unlocked.extend(self._unlock(progress.achievements, "first_level"))
        if progress.play_count >= 10:
            unlocked.extend(self._unlock(progress.achievements, "playful_friend"))
        if progress.focus_minutes >= 60:
            unlocked.extend(self._unlock(progress.achievements, "focus_helper"))
        if reason == "interaction":
            progress.affection_points += 1
        return ProgressionResult(amount, before, progress.level, tuple(unlocked))

    def interact(self, state: PetRuntimeState) -> ProgressionResult:
        state.progression.play_count += 1
        return self.award(state, 5, reason="interaction")

    def complete_focus(self, state: PetRuntimeState, minutes: int) -> ProgressionResult:
        amount = max(0, int(minutes))
        state.progression.focus_minutes += amount
        return self.award(state, min(50, amount * 2), reason="focus")

    def daily_check_in(self, state: PetRuntimeState, *, today: date | None = None) -> ProgressionResult:
        current = (today or date.today()).isoformat()
        progress = state.progression
        if progress.last_daily_date == current:
            return ProgressionResult(0, progress.level, progress.level)
        progress.last_daily_date = current
        progress.daily_streak += 1
        progress.inventory["snack"] = progress.inventory.get("snack", 0) + 1
        return self.award(state, 10, reason="daily")

    @staticmethod
    def add_item(state: PetRuntimeState, item: str, count: int = 1) -> int:
        name = item.strip().lower()
        if not name:
            raise ValueError("Item name cannot be empty")
        quantity = max(0, int(count))
        state.progression.inventory[name] = state.progression.inventory.get(name, 0) + quantity
        return state.progression.inventory[name]

    @staticmethod
    def use_item(state: PetRuntimeState, item: str) -> bool:
        name = item.strip().lower()
        available = state.progression.inventory.get(name, 0)
        if available <= 0:
            return False
        if available == 1:
            state.progression.inventory.pop(name, None)
        else:
            state.progression.inventory[name] = available - 1
        if name == "snack":
            state.needs.energy = min(1.0, state.needs.energy + 0.12)
            state.emotion.valence = min(1.0, state.emotion.valence + 0.08)
        elif name in {"ball", "toy"}:
            state.needs.boredom = max(0.0, state.needs.boredom - 0.25)
            state.emotion.arousal = min(1.0, state.emotion.arousal + 0.12)
        return True

    @staticmethod
    def _unlock(achievements: list[str], name: str) -> list[str]:
        if name in achievements:
            return []
        achievements.append(name)
        return [name]
