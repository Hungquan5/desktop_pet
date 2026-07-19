from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from vla_pet.awareness import (
    AwarenessService,
    AwarenessSettings,
    DesktopContext,
    ProactivePolicy,
)
from vla_pet.permissions import Capability, PermissionBroker


class FakeProbe:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def active_window(self) -> tuple[str, str]:
        self.calls.append("window")
        return "Editor", "secret project"

    def user_idle_seconds(self) -> float:
        self.calls.append("idle")
        return 120.0

    def system_status(self) -> tuple[int, bool, bool]:
        self.calls.append("system")
        return 12, True, True

    def coding_status(self) -> str:
        self.calls.append("coding")
        return "completed"


def test_awareness_never_touches_disabled_or_denied_sensors() -> None:
    probe = FakeProbe()
    service = AwarenessService(probe, PermissionBroker(), AwarenessSettings())
    context = service.sample()
    assert probe.calls == [] and context.active_application == ""
    enabled = AwarenessSettings(active_window=True, user_idle=True, system_status=True)
    context = AwarenessService(probe, PermissionBroker(), enabled).sample()
    assert probe.calls == [] and context.user_idle_seconds is None


def test_awareness_scopes_privacy_and_denied_applications() -> None:
    probe = FakeProbe()
    broker = PermissionBroker(
        {Capability.ACTIVE_WINDOW_READ, Capability.USER_IDLE_READ, Capability.SYSTEM_STATUS_READ}
    )
    settings = AwarenessSettings(
        active_window=True,
        user_idle=True,
        system_status=True,
        coding_status=True,
        denied_title_fragments=("secret",),
    )
    service = AwarenessService(probe, broker, settings)
    context = service.sample()
    assert context.active_application == "" and context.window_title == ""
    assert context.user_idle_seconds == 120 and context.battery_percent == 12
    calls = len(probe.calls)
    private = service.sample(privacy_mode=True)
    assert len(probe.calls) == calls and private.battery_percent is None


def test_proactive_policy_is_explainable_quiet_and_rate_limited() -> None:
    policy = ProactivePolicy(cooldown_s=60, max_per_hour=2)
    settings = AwarenessSettings(proactive=True, quiet_hour_start=23, quiet_hour_end=7)
    context = DesktopContext(1000.0, focus_seconds=5400)
    reaction = policy.evaluate(context, settings, now=datetime(2026, 7, 19, 12, tzinfo=timezone.utc))
    assert reaction is not None and "90 minutes" in reaction.reason
    assert policy.evaluate(replace(context, sampled_at=1030), settings, now=datetime(2026, 7, 19, 12, tzinfo=timezone.utc)) is None
    quiet = replace(context, sampled_at=2000)
    assert policy.evaluate(quiet, settings, now=datetime(2026, 7, 19, 23, 30, tzinfo=timezone.utc)) is None
