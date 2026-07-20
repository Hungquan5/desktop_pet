from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from vla_pet.growth import GrowthEngine, GrowthStage
from vla_pet.state import PetRuntimeState


@dataclass(frozen=True, slots=True)
class ProgressionResult:
    xp_awarded: int
    level_before: int
    level_after: int
    unlocked: tuple[str, ...] = ()
    stage_before: GrowthStage = GrowthStage.BABY
    stage_after: GrowthStage = GrowthStage.BABY
    stat_gains: tuple[tuple[str, int], ...] = ()

    @property
    def evolved(self) -> bool:
        return self.stage_before is not self.stage_after


class ProgressionEngine:
    """Deterministic, non-punishing rewards for interaction and focus."""

    LEVEL_STEP = 100
    DURABLE_ITEMS = frozenset({"ball", "toy"})

    def __init__(self) -> None:
        self.growth = GrowthEngine()

    def award(self, state: PetRuntimeState, xp: int, *, reason: str = "") -> ProgressionResult:
        progress = state.progression
        before = progress.level
        stage_before = GrowthStage(state.growth.stage)
        amount = max(0, int(xp))
        progress.xp += amount
        progress.level = max(progress.level, 1 + progress.xp // self.LEVEL_STEP)
        unlocked: list[str] = []
        if progress.level >= 2:
            unlocked.extend(self._unlock(progress.achievements, "first_level"))
        if progress.play_count >= 10:
            unlocked.extend(self._unlock(progress.achievements, "playful_friend"))
        if progress.focus_minutes >= 60:
            unlocked.extend(self._unlock(progress.achievements, "focus_helper"))
        if reason == "interaction":
            progress.affection_points += 1
        elif reason.startswith("interaction:"):
            progress.affection_points += 1

        magnitude = self._activity_magnitude(reason, amount)
        activity_gains = self.growth.award_activity(state, reason or "progress", magnitude=magnitude)
        transition = self.growth.reconcile(state)
        if transition.evolved:
            unlocked.extend(
                self._unlock(progress.achievements, f"evolved_{transition.after.value}")
            )
        return ProgressionResult(
            amount,
            before,
            progress.level,
            tuple(unlocked),
            stage_before,
            transition.after,
            self._merge_gains(activity_gains, transition.stat_gains),
        )

    def interact(self, state: PetRuntimeState, *, activity: str = "interaction") -> ProgressionResult:
        name = str(activity).strip().lower() or "interaction"
        if any(token in name for token in ("ball", "fetch", "chase", "play", "minigame")):
            state.progression.play_count += 1
        return self.award(state, 5, reason=f"interaction:{name}")

    def complete_focus(self, state: PetRuntimeState, minutes: int) -> ProgressionResult:
        amount = max(0, int(minutes))
        state.progression.focus_minutes += amount
        return self.award(state, min(50, amount * 2), reason="focus")

    def daily_check_in(self, state: PetRuntimeState, *, today: date | None = None) -> ProgressionResult:
        current = (today or date.today()).isoformat()
        progress = state.progression
        if progress.last_daily_date == current:
            stage = GrowthStage(state.growth.stage)
            return ProgressionResult(0, progress.level, progress.level, stage_before=stage, stage_after=stage)
        previous = None
        try:
            previous = date.fromisoformat(progress.last_daily_date)
        except (TypeError, ValueError):
            pass
        progress.last_daily_date = current
        current_date = today or date.today()
        progress.daily_streak = (
            progress.daily_streak + 1
            if previous == current_date - timedelta(days=1)
            else 1
        )
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
        if name not in ProgressionEngine.DURABLE_ITEMS:
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
    def _activity_magnitude(reason: str, xp: int) -> int:
        if reason == "focus":
            return max(4, xp // 2)
        if reason == "daily":
            return 6
        if reason == "minigame":
            return max(4, xp)
        if reason.startswith("item"):
            return 6
        if reason.startswith("interaction:"):
            return 3
        return max(1, xp // 5)

    @staticmethod
    def _merge_gains(
        first: tuple[tuple[str, int], ...],
        second: tuple[tuple[str, int], ...],
    ) -> tuple[tuple[str, int], ...]:
        merged: dict[str, int] = {}
        for name, amount in (*first, *second):
            merged[name] = merged.get(name, 0) + amount
        return tuple((name, amount) for name, amount in merged.items() if amount > 0)

    @staticmethod
    def _unlock(achievements: list[str], name: str) -> list[str]:
        if name in achievements:
            return []
        achievements.append(name)
        return [name]
