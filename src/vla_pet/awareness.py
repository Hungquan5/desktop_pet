from __future__ import annotations

import json
import os
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from vla_pet.permissions import Capability, PermissionBroker


@dataclass(frozen=True, slots=True)
class DesktopContext:
    sampled_at: float
    active_application: str = ""
    window_title: str = ""
    user_idle_seconds: float | None = None
    battery_percent: int | None = None
    on_battery: bool | None = None
    network_available: bool | None = None
    coding_status: str = ""
    focus_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class AwarenessSettings:
    active_window: bool = False
    user_idle: bool = False
    system_status: bool = False
    coding_status: bool = False
    proactive: bool = False
    denied_applications: tuple[str, ...] = ()
    denied_title_fragments: tuple[str, ...] = ()
    quiet_hour_start: int = 22
    quiet_hour_end: int = 8


@dataclass(frozen=True, slots=True)
class ProactiveReaction:
    kind: str
    message: str
    reason: str
    created_at: float


class ContextProbe(Protocol):
    def active_window(self) -> tuple[str, str]: ...

    def user_idle_seconds(self) -> float | None: ...

    def system_status(self) -> tuple[int | None, bool | None, bool | None]: ...

    def coding_status(self) -> str: ...


class LinuxContextProbe:
    """Best-effort inexpensive metadata probes; never captures pixels."""

    def __init__(self, *, coding_marker: Path | None = None) -> None:
        self.coding_marker = coding_marker

    def active_window(self) -> tuple[str, str]:
        if os.environ.get("XDG_SESSION_TYPE", "").casefold() == "wayland":
            helper = Path(__file__).with_name("atspi_probe.py")
            system_python = Path("/usr/bin/python3")
            if not helper.is_file() or not system_python.is_file():
                return "", ""
            try:
                value = json.loads(
                    subprocess.run(
                        [str(system_python), str(helper)],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=1.0,
                    ).stdout
                )
                return str(value.get("application", ""))[:200], str(value.get("title", ""))[:500]
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
                return "", ""
        try:
            window_id = self._run(("xdotool", "getactivewindow"))
            title = self._run(("xdotool", "getwindowname", window_id))
            application = self._run(("xdotool", "getwindowclassname", window_id))
            return application[:200], title[:500]
        except (OSError, subprocess.SubprocessError):
            return "", ""

    def user_idle_seconds(self) -> float | None:
        if os.environ.get("XDG_SESSION_TYPE", "").casefold() == "wayland":
            try:
                value = self._run(
                    (
                        "gdbus",
                        "call",
                        "--session",
                        "--dest",
                        "org.gnome.Mutter.IdleMonitor",
                        "--object-path",
                        "/org/gnome/Mutter/IdleMonitor/Core",
                        "--method",
                        "org.gnome.Mutter.IdleMonitor.GetIdletime",
                    )
                )
                digits = "".join(character for character in value if character.isdigit())
                return float(digits) / 1000.0 if digits else None
            except (OSError, subprocess.SubprocessError, ValueError):
                return None
        try:
            return max(0.0, float(self._run(("xprintidle",))) / 1000.0)
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    def system_status(self) -> tuple[int | None, bool | None, bool | None]:
        battery_percent: int | None = None
        on_battery: bool | None = None
        supplies = Path("/sys/class/power_supply")
        if supplies.is_dir():
            for battery in supplies.glob("BAT*"):
                try:
                    battery_percent = int((battery / "capacity").read_text().strip())
                    status = (battery / "status").read_text().strip().casefold()
                    on_battery = status == "discharging"
                    break
                except (OSError, ValueError):
                    continue
        network_available: bool | None = None
        network = Path("/sys/class/net")
        if network.is_dir():
            states: list[bool] = []
            for interface in network.iterdir():
                if interface.name == "lo":
                    continue
                try:
                    states.append((interface / "operstate").read_text().strip() == "up")
                except OSError:
                    continue
            network_available = any(states) if states else None
        return battery_percent, on_battery, network_available

    def coding_status(self) -> str:
        if self.coding_marker is None:
            return ""
        try:
            value = self.coding_marker.read_text(encoding="utf-8").strip().casefold()
        except OSError:
            return ""
        return value if value in {"running", "waiting", "completed", "failed"} else ""

    @staticmethod
    def _run(command: tuple[str, ...]) -> str:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=0.5,
        ).stdout.strip()


class AwarenessService:
    def __init__(
        self,
        probe: ContextProbe,
        broker: PermissionBroker,
        settings: AwarenessSettings,
    ) -> None:
        self.probe = probe
        self.broker = broker
        self.settings = settings

    def sample(self, *, focus_seconds: float = 0.0, privacy_mode: bool = False) -> DesktopContext:
        now = time.time()
        if privacy_mode:
            return DesktopContext(now, focus_seconds=focus_seconds)
        application = title = coding = ""
        idle: float | None = None
        battery: int | None = None
        on_battery: bool | None = None
        network: bool | None = None
        if self.settings.active_window and self.broker.permits(Capability.ACTIVE_WINDOW_READ):
            application, title = self.probe.active_window()
            if self._blocked(application, title):
                application = title = ""
        if self.settings.user_idle and self.broker.permits(Capability.USER_IDLE_READ):
            idle = self.probe.user_idle_seconds()
        if self.settings.system_status and self.broker.permits(Capability.SYSTEM_STATUS_READ):
            battery, on_battery, network = self.probe.system_status()
        if self.settings.coding_status and self.broker.permits(Capability.ACTIVE_WINDOW_READ):
            coding = self.probe.coding_status()
        return DesktopContext(
            now,
            application,
            title,
            idle,
            battery,
            on_battery,
            network,
            coding,
            max(0.0, focus_seconds),
        )

    def _blocked(self, application: str, title: str) -> bool:
        application_name = application.casefold()
        title_value = title.casefold()
        return any(item.casefold() in application_name for item in self.settings.denied_applications) or any(
            item.casefold() in title_value for item in self.settings.denied_title_fragments
        )


class ProactivePolicy:
    """Explainable rate-limited reactions from metadata, never raw perception."""

    def __init__(self, *, cooldown_s: float = 900.0, max_per_hour: int = 3) -> None:
        self.cooldown_s = max(1.0, cooldown_s)
        self.max_per_hour = max(1, max_per_hour)
        self._last_kind: dict[str, float] = {}
        self._history: deque[float] = deque()
        self._last_coding_status = ""

    def evaluate(
        self,
        context: DesktopContext,
        settings: AwarenessSettings,
        *,
        now: datetime | None = None,
    ) -> ProactiveReaction | None:
        if not settings.proactive:
            return None
        local_now = now or datetime.now().astimezone()
        if self._quiet(local_now.hour, settings.quiet_hour_start, settings.quiet_hour_end):
            return None
        timestamp = context.sampled_at
        while self._history and timestamp - self._history[0] >= 3600.0:
            self._history.popleft()
        if len(self._history) >= self.max_per_hour:
            return None
        candidate: tuple[str, str, str] | None = None
        if context.focus_seconds >= 90 * 60:
            candidate = (
                "focus_break",
                "You have been focusing for 90 minutes. Would you like a short break?",
                "focus timer reached 90 minutes",
            )
        elif context.coding_status in {"completed", "failed", "waiting"} and (
            context.coding_status != self._last_coding_status
        ):
            messages = {
                "completed": "Your coding task finished—nice work!",
                "failed": "Your coding task reported a failure. Want to inspect it together?",
                "waiting": "Your coding task is waiting for input.",
            }
            candidate = (
                f"coding_{context.coding_status}",
                messages[context.coding_status],
                f"coding status changed to {context.coding_status}",
            )
        elif context.on_battery and context.battery_percent is not None and context.battery_percent <= 15:
            candidate = (
                "battery_low",
                f"Battery is at {context.battery_percent}%. It may be time to plug in.",
                "battery status is low",
            )
        self._last_coding_status = context.coding_status
        if candidate is None:
            return None
        kind, message, reason = candidate
        if timestamp - self._last_kind.get(kind, float("-inf")) < self.cooldown_s:
            return None
        self._last_kind[kind] = timestamp
        self._history.append(timestamp)
        return ProactiveReaction(kind, message, reason, timestamp)

    @staticmethod
    def _quiet(hour: int, start: int, end: int) -> bool:
        start %= 24
        end %= 24
        return start <= hour < end if start < end else hour >= start or hour < end
