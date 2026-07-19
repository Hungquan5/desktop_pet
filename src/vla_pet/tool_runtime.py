from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from vla_pet.errors import ErrorCategory, PetError, error_diagnostic
from vla_pet.permissions import Capability, PermissionBroker
from vla_pet.persistence import StateRepository


class ToolRisk(str, Enum):
    AUTO_SAFE = "auto_safe"
    READ_ALLOWED = "read_allowed"
    CONFIRM_ONCE = "confirm_once"
    CONFIRM_EACH = "confirm_each"
    RESTRICTED = "restricted"


@dataclass(frozen=True, slots=True)
class ToolManifest:
    name: str
    description: str
    input_schema: dict[str, Any]
    risk: ToolRisk
    capability: Capability
    timeout_s: float = 10.0
    subject: str = "core"
    visible_indicator: bool = True

    def validate(self) -> None:
        if not self.name or not all(part.replace("_", "").isalnum() for part in self.name.split(".")):
            raise ValueError("Tool name must be a dotted identifier")
        if self.input_schema.get("type") != "object":
            raise ValueError("Tool input schema must describe an object")
        if not 0.05 <= float(self.timeout_s) <= 300.0:
            raise ValueError("Tool timeout is outside the supported range")


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    name: str
    arguments: dict[str, Any]
    subject: str = "core"
    explicit_user_action: bool = False
    reason: str = ""
    invocation_id: str = field(default_factory=lambda: f"tool_{uuid4().hex}")
    trace_id: str = field(default_factory=lambda: f"trace_{uuid4().hex}")


@dataclass(frozen=True, slots=True)
class ToolResult:
    invocation_id: str
    tool_name: str
    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    duration_ms: float = 0.0


ToolHandler = Callable[[Mapping[str, Any]], ToolResult | tuple[str, dict[str, Any]] | str]
ScopeBuilder = Callable[[Mapping[str, Any]], Mapping[str, object]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolManifest, ToolHandler, ScopeBuilder]] = {}

    def register(
        self,
        manifest: ToolManifest,
        handler: ToolHandler,
        *,
        scope_builder: ScopeBuilder | None = None,
    ) -> None:
        manifest.validate()
        if manifest.name in self._tools:
            raise ValueError(f"Tool already registered: {manifest.name}")
        self._tools[manifest.name] = (manifest, handler, scope_builder or (lambda _args: {}))

    def resolve(self, name: str) -> tuple[ToolManifest, ToolHandler, ScopeBuilder]:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise PetError(
                ErrorCategory.CONFIGURATION,
                "tool.not_found",
                f"Unknown tool: {name}",
            ) from exc

    def manifests(self) -> tuple[ToolManifest, ...]:
        return tuple(item[0] for item in self._tools.values())


class ToolHost:
    """Capability gate and redacted audit boundary for every tool handler."""

    def __init__(
        self,
        registry: ToolRegistry,
        broker: PermissionBroker,
        *,
        repository: StateRepository | None = None,
    ) -> None:
        self.registry = registry
        self.broker = broker
        self.repository = repository

    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        started = time.monotonic()
        manifest, handler, scope_builder = self.registry.resolve(invocation.name)
        scope = dict(scope_builder(invocation.arguments))
        decision = "deny"
        status = "denied"
        error_code = ""
        grant = None
        try:
            self._validate_arguments(manifest.input_schema, invocation.arguments)
            if self.broker.safe_mode:
                raise PetError(
                    ErrorCategory.PERMISSION_DENIED,
                    "tool.safe_mode.denied",
                    "Tools are disabled in safe mode",
                )
            grant = self.broker.matching_grant(
                manifest.capability,
                subject=manifest.subject,
                scope=scope,
            )
            raw = self.broker.run_authorized(
                manifest.capability,
                lambda: handler(invocation.arguments),
                explicit_user_action=invocation.explicit_user_action,
                subject=manifest.subject,
                scope=scope,
            )
            decision = "allow"
            elapsed = (time.monotonic() - started) * 1000.0
            if elapsed > manifest.timeout_s * 1000.0:
                raise PetError(
                    ErrorCategory.WORKER_TIMEOUT,
                    "tool.timeout",
                    f"Tool exceeded its {manifest.timeout_s:.1f}s timeout",
                )
            result = self._coerce_result(invocation, raw, elapsed)
            status = "ok" if result.ok else "error"
            error_code = result.error_code
            return result
        except Exception as exc:
            elapsed = (time.monotonic() - started) * 1000.0
            diagnostic = error_diagnostic(exc, "tool")
            error_code = str(diagnostic["code"])
            status = "denied" if isinstance(exc, PetError) and (
                exc.category is ErrorCategory.PERMISSION_DENIED
            ) else "error"
            return ToolResult(
                invocation.invocation_id,
                invocation.name,
                False,
                "The tool was not run." if status == "denied" else "The tool could not finish.",
                error_code=error_code,
                duration_ms=elapsed,
            )
        finally:
            if self.repository is not None:
                audit_scope = dict(scope)
                if grant is not None:
                    audit_scope.update(
                        {
                            "permission_grant_id": grant.grant_id,
                            "permission_lifetime": grant.lifetime.value,
                            "permission_reason": grant.reason,
                        }
                    )
                self.repository.record_tool_audit(
                    {
                        "invocation_id": invocation.invocation_id,
                        "tool_name": invocation.name,
                        "subject": manifest.subject,
                        "capability": manifest.capability.value,
                        "scope": audit_scope,
                        "decision": decision,
                        "status": status,
                        "duration_ms": (time.monotonic() - started) * 1000.0,
                        "error_code": error_code,
                        "trace_id": invocation.trace_id,
                        "risk": manifest.risk.value,
                        "reason_chars": len(invocation.reason),
                        "input_keys": sorted(invocation.arguments),
                    }
                )

    @staticmethod
    def _validate_arguments(schema: dict[str, Any], arguments: Mapping[str, Any]) -> None:
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        if not isinstance(arguments, Mapping):
            raise ValueError("Tool arguments must be an object")
        missing = [name for name in required if name not in arguments]
        if missing:
            raise ValueError(f"Missing tool arguments: {', '.join(missing)}")
        types = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "object": Mapping,
            "array": (list, tuple),
        }
        for key, value in arguments.items():
            if key not in properties:
                raise ValueError(f"Unexpected tool argument: {key}")
            expected = types.get(properties[key].get("type"))
            if expected and (not isinstance(value, expected) or isinstance(value, bool) and expected is int):
                raise ValueError(f"Invalid type for tool argument: {key}")

    @staticmethod
    def _coerce_result(
        invocation: ToolInvocation,
        value: ToolResult | tuple[str, dict[str, Any]] | str,
        duration_ms: float,
    ) -> ToolResult:
        if isinstance(value, ToolResult):
            return value
        if isinstance(value, tuple):
            summary, data = value
        else:
            summary, data = value, {}
        # Validate serializability and bound result size before it reaches a model/UI.
        encoded = json.dumps(data, ensure_ascii=False, default=str)
        if len(encoded.encode("utf-8")) > 64 * 1024:
            raise ValueError("Tool result exceeds the 64 KiB boundary")
        return ToolResult(
            invocation.invocation_id,
            invocation.name,
            True,
            str(summary)[:1000],
            json.loads(encoded),
            duration_ms=duration_ms,
        )


def approved_path_scope(arguments: Mapping[str, Any]) -> Mapping[str, object]:
    value = Path(str(arguments.get("path", ""))).expanduser().resolve()
    return {"path": str(value)}
