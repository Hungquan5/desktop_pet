from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vla_pet.state import PetRuntimeState


class GrowthStage(str, Enum):
    BABY = "baby"
    CHILD = "child"
    TEEN = "teen"


class StatKind(str, Enum):
    HEALTH = "health"
    STAMINA = "stamina"
    INTELLIGENCE = "intelligence"


@dataclass(frozen=True, slots=True)
class StageDefinition:
    stage: GrowthStage
    display_name: str
    minimum_xp: int
    sprite_scale: float
    stat_bonus: int


STAGE_DEFINITIONS = (
    StageDefinition(GrowthStage.BABY, "Baby", 0, 0.90, 0),
    StageDefinition(GrowthStage.CHILD, "Child", 300, 1.00, 3),
    StageDefinition(GrowthStage.TEEN, "Teen", 1000, 1.18, 5),
)
_STAGE_INDEX = {definition.stage: index for index, definition in enumerate(STAGE_DEFINITIONS)}


@dataclass(frozen=True, slots=True)
class StageProgress:
    stage: GrowthStage
    display_name: str
    earned: int
    required: int
    ratio: float
    next_stage: GrowthStage | None


@dataclass(frozen=True, slots=True)
class GrowthTransition:
    before: GrowthStage
    after: GrowthStage
    stat_gains: tuple[tuple[str, int], ...] = ()

    @property
    def evolved(self) -> bool:
        return self.before is not self.after


def stage_for_xp(xp: int) -> GrowthStage:
    amount = max(0, int(xp))
    return next(
        definition.stage
        for definition in reversed(STAGE_DEFINITIONS)
        if amount >= definition.minimum_xp
    )


def stage_definition(stage: GrowthStage | str) -> StageDefinition:
    try:
        normalized = stage if isinstance(stage, GrowthStage) else GrowthStage(str(stage))
    except ValueError:
        normalized = GrowthStage.BABY
    return STAGE_DEFINITIONS[_STAGE_INDEX[normalized]]


def stage_progress(xp: int, stage: GrowthStage | str | None = None) -> StageProgress:
    amount = max(0, int(xp))
    current = stage_for_xp(amount) if stage is None else stage_definition(stage).stage
    index = _STAGE_INDEX[current]
    definition = STAGE_DEFINITIONS[index]
    if index == len(STAGE_DEFINITIONS) - 1:
        return StageProgress(current, definition.display_name, 1, 1, 1.0, None)
    next_definition = STAGE_DEFINITIONS[index + 1]
    earned = max(0, amount - definition.minimum_xp)
    required = next_definition.minimum_xp - definition.minimum_xp
    return StageProgress(
        current,
        definition.display_name,
        min(required, earned),
        required,
        min(1.0, earned / required),
        next_definition.stage,
    )


class GrowthEngine:
    """Positive-only form and RPG-stat growth driven by completed activities."""

    STAT_CAP = 99

    @staticmethod
    def stat_threshold(value: int) -> int:
        return 20 + max(0, int(value) - 5) * 3

    def reconcile(self, state: PetRuntimeState) -> GrowthTransition:
        state.growth.normalize()
        state.stats.normalize()
        before = GrowthStage(state.growth.stage)
        target = stage_for_xp(state.progression.xp)
        before_index = _STAGE_INDEX[before]
        target_index = _STAGE_INDEX[target]
        if target_index <= before_index:
            return GrowthTransition(before, before)

        stat_before = self._stat_values(state)
        for definition in STAGE_DEFINITIONS[before_index + 1 : target_index + 1]:
            for kind in StatKind:
                current = getattr(state.stats, kind.value)
                setattr(state.stats, kind.value, min(self.STAT_CAP, current + definition.stat_bonus))
            state.growth.stage = definition.stage.value
            state.growth.last_evolution_xp = state.progression.xp
            if definition.stage.value not in state.growth.evolution_history:
                state.growth.evolution_history.append(definition.stage.value)
        return GrowthTransition(before, target, self._stat_diff(stat_before, state))

    def award_activity(
        self,
        state: PetRuntimeState,
        activity: str,
        *,
        magnitude: int = 1,
    ) -> tuple[tuple[str, int], ...]:
        key = str(activity).strip().lower()
        amount = max(1, int(magnitude))
        awards = {kind: 1 for kind in StatKind}
        if "focus" in key or "study" in key or "chat" in key:
            awards = {StatKind.HEALTH: 0, StatKind.STAMINA: 0, StatKind.INTELLIGENCE: amount}
        elif any(token in key for token in ("ball", "fetch", "chase", "play", "minigame")):
            awards = {StatKind.HEALTH: 0, StatKind.STAMINA: amount, StatKind.INTELLIGENCE: 1}
        elif any(token in key for token in ("snack", "rest", "sleep", "daily")):
            awards = {StatKind.HEALTH: amount, StatKind.STAMINA: 1, StatKind.INTELLIGENCE: 1}
        elif "box" in key or "inspect" in key:
            awards = {StatKind.HEALTH: 0, StatKind.STAMINA: 1, StatKind.INTELLIGENCE: amount}
        return self.award_stat_experience(state, awards)

    def award_stat_experience(
        self,
        state: PetRuntimeState,
        awards: dict[StatKind, int],
    ) -> tuple[tuple[str, int], ...]:
        state.stats.normalize()
        before = self._stat_values(state)
        for kind in StatKind:
            value_name = kind.value
            xp_name = f"{kind.value}_xp"
            experience = getattr(state.stats, xp_name) + max(0, int(awards.get(kind, 0)))
            value = getattr(state.stats, value_name)
            while value < self.STAT_CAP:
                threshold = self.stat_threshold(value)
                if experience < threshold:
                    break
                experience -= threshold
                value += 1
            if value >= self.STAT_CAP:
                experience = 0
            setattr(state.stats, value_name, value)
            setattr(state.stats, xp_name, experience)
        return self._stat_diff(before, state)

    @staticmethod
    def _stat_values(state: PetRuntimeState) -> dict[str, int]:
        return {kind.value: int(getattr(state.stats, kind.value)) for kind in StatKind}

    @staticmethod
    def _stat_diff(before: dict[str, int], state: PetRuntimeState) -> tuple[tuple[str, int], ...]:
        return tuple(
            (kind.value, int(getattr(state.stats, kind.value)) - before[kind.value])
            for kind in StatKind
            if int(getattr(state.stats, kind.value)) > before[kind.value]
        )


def companion_status_text(state: PetRuntimeState) -> str:
    definition = stage_definition(state.growth.stage)
    return (
        f"Momo status: form {definition.display_name}; level {state.progression.level}; "
        f"XP {state.progression.xp}; health {state.stats.health}; "
        f"stamina {state.stats.stamina}; intelligence {state.stats.intelligence}."
    )
