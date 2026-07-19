from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from vla_pet.errors import ErrorCategory, PetError


class Capability(str, Enum):
    SCREEN_CAPTURE_EACH_TIME = "screen_capture_each_time"
    NOTIFICATION_MONITOR_SESSION = "notification_monitor_session"
    PERSIST_CONVERSATION = "persist_conversation"
    AUTOSTART = "autostart"
    CAMERA_CAPTURE = "camera_capture"
    MICROPHONE_CAPTURE = "microphone_capture"
    CLIPBOARD_READ = "clipboard_read"
    FILESYSTEM_READ = "filesystem_read"
    FILESYSTEM_WRITE = "filesystem_write"
    NETWORK_HTTP = "network_http"
    BROWSER_CONTROL = "browser_control"
    DESKTOP_AUTOMATION = "desktop_automation"
    SHELL_EXEC = "shell_exec"
    MEMORY_EXPORT = "memory_export"
    TIMER_MANAGE = "timer_manage"
    TODO_MANAGE = "todo_manage"
    REMINDER_MANAGE = "reminder_manage"
    NOTE_MANAGE = "note_manage"
    APPLICATION_OPEN = "application_open"
    ACTIVE_WINDOW_READ = "active_window_read"
    USER_IDLE_READ = "user_idle_read"
    SYSTEM_STATUS_READ = "system_status_read"
    PLUGIN_EXECUTE = "plugin_execute"
    MCP_CONNECT = "mcp_connect"
    UPDATE_CHECK = "update_check"


class PermissionLifetime(str, Enum):
    ONCE = "once"
    SESSION = "session"
    ALWAYS = "always"


class PermissionDecision(str, Enum):
    ASK = "ask"
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class PermissionGrant:
    capability: Capability
    lifetime: PermissionLifetime = PermissionLifetime.SESSION
    subject: str = "core"
    scope: tuple[tuple[str, str], ...] = ()
    grant_id: str = ""
    reason: str = ""
    granted_at: str = ""


ResultT = TypeVar("ResultT")


class PermissionBroker:
    """In-process capability gate used before every optional platform access.

    Grants remain process-local: session grants disappear on restart, one-shot
    grants are consumed by ``run_authorized``, and safe mode denies every
    capability regardless of prior state. Persisted feature/plugin enablement
    is translated into fresh scoped grants by the composition root.
    """

    def __init__(
        self,
        allowed: Iterable[Capability] = (),
        *,
        safe_mode: bool = False,
    ) -> None:
        self.safe_mode = safe_mode
        self._denials: list[PermissionGrant] = []
        self._grants: list[PermissionGrant] = [
            self._make_grant(capability) for capability in allowed
        ]

    @property
    def allowed(self) -> set[Capability]:
        return {grant.capability for grant in self._grants}

    def grant(
        self,
        capability: Capability,
        *,
        lifetime: PermissionLifetime = PermissionLifetime.SESSION,
        subject: str = "core",
        scope: Mapping[str, object] | None = None,
        reason: str = "",
    ) -> PermissionGrant:
        grant = self._make_grant(
            capability,
            lifetime=lifetime,
            subject=subject,
            scope=scope,
            reason=reason,
        )
        self._denials = [
            denied
            for denied in self._denials
            if not (denied.capability is capability and denied.subject == subject)
        ]
        self._grants.append(grant)
        return grant

    def deny(
        self,
        capability: Capability,
        *,
        subject: str = "core",
        scope: Mapping[str, object] | None = None,
        reason: str = "",
    ) -> PermissionGrant:
        denied = self._make_grant(
            capability,
            lifetime=PermissionLifetime.ALWAYS,
            subject=subject,
            scope=scope,
            reason=reason,
        )
        self.revoke(capability, subject=subject)
        self._denials.append(denied)
        return denied

    def revoke(self, capability: Capability, *, subject: str | None = None) -> int:
        before = len(self._grants)
        self._grants = [
            grant
            for grant in self._grants
            if not (
                grant.capability is capability
                and (subject is None or grant.subject == subject)
            )
        ]
        removed = before - len(self._grants)
        denial_before = len(self._denials)
        self._denials = [
            grant
            for grant in self._denials
            if not (
                grant.capability is capability and (subject is None or grant.subject == subject)
            )
        ]
        return removed + denial_before - len(self._denials)

    def revoke_all(self) -> None:
        self._grants.clear()
        self._denials.clear()

    def permits(
        self,
        capability: Capability,
        *,
        explicit_user_action: bool = False,
        subject: str = "core",
        scope: Mapping[str, object] | None = None,
    ) -> bool:
        if self.safe_mode:
            return False
        requested_scope = self._normalize_scope(scope)
        if any(
            denied.capability is capability
            and denied.subject == subject
            and self._scope_contains(denied.scope, requested_scope)
            for denied in self._denials
        ):
            return False
        if capability is Capability.SCREEN_CAPTURE_EACH_TIME:
            return explicit_user_action
        return self.matching_grant(
            capability,
            subject=subject,
            scope=scope,
        ) is not None

    def matching_grant(
        self,
        capability: Capability,
        *,
        subject: str = "core",
        scope: Mapping[str, object] | None = None,
    ) -> PermissionGrant | None:
        requested_scope = self._normalize_scope(scope)
        return next(
            (
                grant
                for grant in reversed(self._grants)
                if grant.capability is capability
                and grant.subject == subject
                and self._scope_contains(grant.scope, requested_scope)
            ),
            None,
        )

    def require(
        self,
        capability: Capability,
        *,
        explicit_user_action: bool = False,
        subject: str = "core",
        scope: Mapping[str, object] | None = None,
    ) -> None:
        if not self.permits(
            capability,
            explicit_user_action=explicit_user_action,
            subject=subject,
            scope=scope,
        ):
            raise PetError(
                ErrorCategory.PERMISSION_DENIED,
                f"capability.{capability.value}.denied",
                f"Permission is required for {capability.value}",
            )

    def run_authorized(
        self,
        capability: Capability,
        operation: Callable[[], ResultT],
        *,
        explicit_user_action: bool = False,
        subject: str = "core",
        scope: Mapping[str, object] | None = None,
    ) -> ResultT:
        self.require(
            capability,
            explicit_user_action=explicit_user_action,
            subject=subject,
            scope=scope,
        )
        result = operation()
        if capability is not Capability.SCREEN_CAPTURE_EACH_TIME:
            self._consume_once(capability, subject, self._normalize_scope(scope))
        return result

    def snapshot(self) -> tuple[PermissionGrant, ...]:
        return tuple(self._grants)

    def denial_snapshot(self) -> tuple[PermissionGrant, ...]:
        return tuple(self._denials)

    @staticmethod
    def _make_grant(
        capability: Capability,
        *,
        lifetime: PermissionLifetime = PermissionLifetime.SESSION,
        subject: str = "core",
        scope: Mapping[str, object] | None = None,
        reason: str = "",
    ) -> PermissionGrant:
        return PermissionGrant(
            capability=capability,
            lifetime=lifetime,
            subject=subject,
            scope=PermissionBroker._normalize_scope(scope),
            grant_id=f"perm_{uuid4().hex}",
            reason=reason[:240],
            granted_at=datetime.now(timezone.utc).isoformat(),
        )

    def _consume_once(
        self,
        capability: Capability,
        subject: str,
        requested_scope: tuple[tuple[str, str], ...],
    ) -> None:
        for index, grant in enumerate(self._grants):
            if (
                grant.capability is capability
                and grant.subject == subject
                and grant.lifetime is PermissionLifetime.ONCE
                and self._scope_contains(grant.scope, requested_scope)
            ):
                self._grants.pop(index)
                return

    @staticmethod
    def _normalize_scope(scope: Mapping[str, object] | None) -> tuple[tuple[str, str], ...]:
        if not scope:
            return ()
        return tuple(sorted((str(key), str(value)) for key, value in scope.items()))

    @staticmethod
    def _scope_contains(
        granted: tuple[tuple[str, str], ...],
        requested: tuple[tuple[str, str], ...],
    ) -> bool:
        if not requested:
            return True
        granted_values = dict(granted)
        for key, value in requested:
            allowed = granted_values.get(key)
            if allowed is None:
                return False
            if key in {"directory", "path", "root", "workspace"}:
                try:
                    if not Path(value).expanduser().resolve().is_relative_to(
                        Path(allowed).expanduser().resolve()
                    ):
                        return False
                except (OSError, RuntimeError, ValueError):
                    return False
            elif key in {"domain", "application"}:
                choices = {item.strip().casefold() for item in allowed.split(",") if item.strip()}
                if value.casefold() not in choices:
                    return False
            elif allowed != value:
                return False
        return True


class PermissionPolicy(PermissionBroker):
    """Backward-compatible public name for the permission broker."""
