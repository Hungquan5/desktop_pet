from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from vla_pet.contracts import ActionKind, PetAction
from vla_pet.progression import ProgressionEngine
from vla_pet.state import PetRuntimeState


class LifeIntent(str, Enum):
    REST = "rest"
    WALK = "walk"
    PLAY = "play"
    SOCIALIZE = "socialize"
    SLEEP = "sleep"
    CELEBRATE = "celebrate"
    INSPECT = "inspect"
    COMFORT = "comfort"
    FOCUS = "focus"


@dataclass(frozen=True, slots=True)
class LifeDecision:
    intent: LifeIntent
    score: float
    scores: dict[LifeIntent, float]


@dataclass(frozen=True, slots=True)
class LifeContext:
    user_present: bool = True
    user_idle_seconds: float = 0.0
    active_application: str = ""
    recent_notification: bool = False
    focus_active: bool = False
    user_valence_hint: float = 0.0


class LifeEngine:
    """Deterministic needs and utility behavior; no model is required."""

    DECISION_INTERVAL_S = 0.2

    def __init__(self) -> None:
        self._elapsed_since_decision = self.DECISION_INTERVAL_S
        self.progression = ProgressionEngine()

    def tick(
        self,
        state: PetRuntimeState,
        dt: float,
        *,
        user_present: bool = True,
        context: LifeContext | None = None,
    ) -> LifeDecision | None:
        context = context or LifeContext(user_present=user_present)
        user_present = context.user_present
        dt = min(5.0, max(0.0, float(dt)))
        if state.active_intention == LifeIntent.SLEEP.value:
            state.needs.energy += dt * 0.008
        elif state.active_intention == LifeIntent.REST.value:
            state.needs.energy += dt * 0.002
        else:
            state.needs.energy -= dt * 0.00045
        state.needs.boredom += dt * 0.0012
        state.needs.social -= dt * (0.00035 if user_present else 0.00012)
        state.needs.curiosity += dt * 0.0003
        state.needs.clamp()

        state.emotion.valence += (0.15 - state.emotion.valence) * min(1.0, dt * 0.01)
        state.emotion.arousal += (0.25 - state.emotion.arousal) * min(1.0, dt * 0.015)
        state.emotion.clamp()
        state.last_life_tick_at += dt

        self._elapsed_since_decision += dt
        if self._elapsed_since_decision < self.DECISION_INTERVAL_S:
            return None
        self._elapsed_since_decision = 0.0

        scores = {
            LifeIntent.SLEEP: (1.0 - state.needs.energy) * 1.4,
            LifeIntent.PLAY: state.needs.boredom * 0.9 + state.needs.energy * 0.25,
            LifeIntent.SOCIALIZE: (1.0 - state.needs.social) * (0.8 if user_present else 0.25),
            LifeIntent.WALK: state.needs.curiosity * 0.55 + state.needs.energy * 0.2,
            LifeIntent.CELEBRATE: max(0.0, state.emotion.valence) * state.emotion.arousal * 0.8,
            LifeIntent.REST: 0.22 + (1.0 - state.emotion.arousal) * 0.18,
            LifeIntent.INSPECT: (0.75 if context.recent_notification else 0.0)
            + state.needs.curiosity * 0.18,
            LifeIntent.COMFORT: max(0.0, -context.user_valence_hint) * state.emotion.affection,
            LifeIntent.FOCUS: 0.9 if context.focus_active else 0.0,
        }
        intent, score = max(scores.items(), key=lambda item: (item[1], -list(LifeIntent).index(item[0])))
        state.active_intention = intent.value
        state.emotion.tag = self._emotion_tag(state)
        return LifeDecision(intent, score, scores)

    def interact(
        self,
        state: PetRuntimeState,
        *,
        positive: bool = True,
        activity: str = "interaction",
    ) -> None:
        state.interaction_count += 1
        state.relationship_level = min(10, state.interaction_count // 10)
        state.last_interaction_at = state.last_life_tick_at
        state.needs.social = min(1.0, state.needs.social + 0.18)
        state.needs.boredom = max(0.0, state.needs.boredom - 0.12)
        state.needs.energy = min(1.0, state.needs.energy + 0.03)
        state.emotion.affection = min(1.0, state.emotion.affection + 0.01)
        state.emotion.valence = min(1.0, state.emotion.valence + (0.12 if positive else 0.02))
        state.emotion.arousal = min(1.0, state.emotion.arousal + 0.08)
        self.progression.interact(state, activity=activity)

    @staticmethod
    def routine_action(intent: LifeIntent, step: int, facing: int) -> PetAction:
        """Map an intention to a varied, deterministic, model-free routine."""
        step = max(0, int(step))
        if intent is LifeIntent.WALK:
            # Two short walks followed by a visible pause prevents perpetual
            # locomotion while curiosity remains the highest utility.
            kind = ActionKind.IDLE if step % 3 == 2 else ActionKind.WALK
        elif intent is LifeIntent.PLAY:
            kind = (ActionKind.JUMP, ActionKind.IDLE, ActionKind.HAPPY, ActionKind.IDLE)[
                step % 4
            ]
        elif intent in {LifeIntent.SOCIALIZE, LifeIntent.CELEBRATE, LifeIntent.COMFORT}:
            kind = ActionKind.HAPPY if step % 3 == 0 else ActionKind.IDLE
        elif intent is LifeIntent.INSPECT:
            kind = ActionKind.WALK if step % 3 != 2 else ActionKind.IDLE
        elif intent is LifeIntent.FOCUS:
            kind = ActionKind.IDLE
        else:
            kind = ActionKind.IDLE

        durations = {
            ActionKind.WALK: 1.4,
            ActionKind.JUMP: 0.9,
            ActionKind.HAPPY: 0.9,
            ActionKind.IDLE: 1.8 if intent is not LifeIntent.SLEEP else 2.8,
        }
        return PetAction(
            kind,
            direction=facing,
            speed=82.0,
            duration=durations[kind],
            source="life",
            note=f"routine:{intent.value}:{step}",
        )

    @staticmethod
    def _emotion_tag(state: PetRuntimeState) -> str:
        if state.needs.energy < 0.2:
            return "sleepy"
        if state.emotion.valence > 0.55:
            return "happy"
        if state.emotion.valence < -0.3:
            return "sad"
        if state.emotion.arousal > 0.7:
            return "excited"
        return "content"
