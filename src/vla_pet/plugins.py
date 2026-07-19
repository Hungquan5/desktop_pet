from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vla_pet.errors import ErrorCategory, PetError
from vla_pet.permissions import Capability, PermissionBroker
from vla_pet.persistence import StateRepository
from vla_pet.signing import Signature, TrustStore, canonical_json

PLUGIN_API = "pet.dev/v1"


def default_plugin_directory() -> Path:
    source = Path(__file__).resolve().parents[2] / "plugins"
    installed = Path(sys.prefix) / "share" / "vla-pet" / "plugins"
    return source if source.exists() else installed


@dataclass(frozen=True, slots=True)
class PluginPermission:
    capability: Capability
    scope: tuple[tuple[str, str], ...]
    default: str


@dataclass(frozen=True, slots=True)
class PluginManifest:
    name: str
    version: str
    display_name: str
    author: str
    license: str
    root: Path
    runtime: str
    entrypoint: tuple[str, ...]
    permissions: tuple[PluginPermission, ...]
    hooks: tuple[str, ...]
    timeout_ms: int
    max_invocations_per_minute: int
    max_memory_mb: int
    storage_bytes: int
    builtin: bool
    signature_key_id: str = ""

    @classmethod
    def load(
        cls,
        directory: Path,
        *,
        trust_store: TrustStore | None = None,
        trusted_builtin_root: Path | None = None,
    ) -> PluginManifest:
        root = directory.expanduser().resolve()
        manifest_path = root / "plugin.json"
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PetError(
                ErrorCategory.CONFIGURATION,
                "plugin.manifest.unreadable",
                f"Cannot read plugin manifest: {exc}",
            ) from exc
        if raw.get("apiVersion") != PLUGIN_API or raw.get("kind") != "ToolPlugin":
            raise PetError(
                ErrorCategory.CONFIGURATION,
                "plugin.schema.unsupported",
                "Plugin must use pet.dev/v1 ToolPlugin",
            )
        metadata = raw.get("metadata")
        spec = raw.get("spec")
        if not isinstance(metadata, dict) or not isinstance(spec, dict):
            raise PetError(ErrorCategory.CONFIGURATION, "plugin.fields.missing", "Plugin fields missing")
        name = str(metadata.get("name", "")).strip()
        if not name or not all(part.replace("-", "").isalnum() for part in name.split(".")):
            raise PetError(ErrorCategory.CONFIGURATION, "plugin.name.invalid", "Invalid plugin name")
        builtin = bool(metadata.get("builtin", False))
        trusted_builtin = bool(
            builtin
            and trusted_builtin_root is not None
            and root.is_relative_to(trusted_builtin_root.expanduser().resolve())
        )
        cls._verify_integrity(root, raw.get("integrity"))
        signature_key_id = ""
        if not trusted_builtin:
            signature_raw = raw.get("signature")
            if not isinstance(signature_raw, dict) or trust_store is None:
                raise PetError(
                    ErrorCategory.PERMISSION_DENIED,
                    "plugin.signature.required",
                    "Third-party plugins require a trusted Ed25519 signature",
                )
            unsigned = dict(raw)
            unsigned.pop("signature", None)
            signature = Signature(
                str(signature_raw.get("key_id", "")),
                str(signature_raw.get("value", "")),
                str(signature_raw.get("algorithm", "ed25519")),
            )
            if not trust_store.verify(canonical_json(unsigned), signature):
                raise PetError(
                    ErrorCategory.PERMISSION_DENIED,
                    "plugin.signature.invalid",
                    "Plugin signature is invalid or untrusted",
                )
            signature_key_id = signature.key_id
        permissions_raw = spec.get("permissions")
        if not isinstance(permissions_raw, list):
            raise PetError(
                ErrorCategory.CONFIGURATION,
                "plugin.permissions.missing",
                "Plugin permissions must be declared",
            )
        permissions: list[PluginPermission] = []
        for item in permissions_raw:
            if not isinstance(item, dict):
                raise PetError(ErrorCategory.CONFIGURATION, "plugin.permission.invalid", "Invalid permission")
            try:
                capability = Capability(str(item["capability"]))
            except (KeyError, ValueError) as exc:
                raise PetError(
                    ErrorCategory.CONFIGURATION,
                    "plugin.permission.unknown",
                    "Plugin declares an unknown capability",
                ) from exc
            scope = item.get("scope", {})
            if not isinstance(scope, dict):
                raise PetError(ErrorCategory.CONFIGURATION, "plugin.scope.invalid", "Invalid scope")
            permissions.append(
                PluginPermission(
                    capability,
                    tuple(sorted((str(key), str(value)) for key, value in scope.items())),
                    str(item.get("default", "ask")),
                )
            )
        runtime = str(spec.get("runtime", ""))
        if runtime not in {"builtin", "python-subprocess", "mcp-stdio"}:
            raise PetError(ErrorCategory.CONFIGURATION, "plugin.runtime.invalid", "Invalid plugin runtime")
        entrypoint_raw = spec.get("entrypoint", [])
        if not isinstance(entrypoint_raw, list) or not all(
            isinstance(item, str) and item for item in entrypoint_raw
        ):
            raise PetError(ErrorCategory.CONFIGURATION, "plugin.entrypoint.invalid", "Invalid entrypoint")
        for item in entrypoint_raw:
            if Path(item).is_absolute() or ".." in Path(item).parts:
                raise PetError(ErrorCategory.CONFIGURATION, "plugin.entrypoint.unsafe", "Unsafe entrypoint")
        quotas = spec.get("quotas", {})
        storage = spec.get("storage", {})
        return cls(
            name=name,
            version=str(metadata.get("version", "0.0.0")),
            display_name=str(metadata.get("displayName", name)),
            author=str(metadata.get("author", "unknown")),
            license=str(metadata.get("license", "UNSPECIFIED")),
            root=root,
            runtime=runtime,
            entrypoint=tuple(entrypoint_raw),
            permissions=tuple(permissions),
            hooks=tuple(str(item) for item in spec.get("hooks", [])),
            timeout_ms=max(100, min(300_000, int(quotas.get("timeoutMs", 15_000)))),
            max_invocations_per_minute=max(
                1, min(600, int(quotas.get("maxInvocationsPerMinute", 10)))
            ),
            max_memory_mb=max(32, min(2048, int(quotas.get("maxMemoryMb", 256)))),
            storage_bytes=max(0, min(100 * 1024 * 1024, int(storage.get("maxBytes", 1_048_576)))),
            builtin=builtin,
            signature_key_id=signature_key_id,
        )

    @staticmethod
    def _verify_integrity(root: Path, value: Any) -> None:
        if not isinstance(value, dict) or not value:
            raise PetError(
                ErrorCategory.CONFIGURATION,
                "plugin.integrity.missing",
                "Plugin must declare SHA-256 file integrity",
            )
        for relative, expected in value.items():
            path = root / str(relative)
            try:
                resolved = path.resolve()
            except OSError as exc:
                raise PetError(ErrorCategory.CONFIGURATION, "plugin.file.invalid", str(exc)) from exc
            if not resolved.is_relative_to(root) or not resolved.is_file():
                raise PetError(ErrorCategory.CONFIGURATION, "plugin.file.unsafe", "Unsafe plugin file")
            digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
            if not str(expected).startswith("sha256:") or digest != str(expected)[7:]:
                raise PetError(
                    ErrorCategory.PERMISSION_DENIED,
                    "plugin.integrity.invalid",
                    f"Plugin file integrity failed: {relative}",
                )


class PluginSandbox:
    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or shutil.which("bwrap") or ""

    @property
    def available(self) -> bool:
        return bool(self.executable and Path(self.executable).is_file())

    def command(self, manifest: PluginManifest, *, allow_network: bool = False) -> list[str]:
        if not self.available:
            raise PetError(
                ErrorCategory.PLATFORM_UNAVAILABLE,
                "plugin.sandbox.unavailable",
                "Third-party plugin execution requires bubblewrap on Linux",
            )
        if manifest.runtime != "python-subprocess" or not manifest.entrypoint:
            raise ValueError("Manifest is not an executable Python plugin")
        script = (manifest.root / manifest.entrypoint[0]).resolve()
        if not script.is_relative_to(manifest.root) or not script.is_file():
            raise ValueError("Plugin entrypoint is missing or unsafe")
        command = [
            self.executable,
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/lib",
            "/lib",
            "--ro-bind",
            sys.prefix,
            "/runtime",
        ]
        if Path("/lib64").exists():
            command.extend(("--ro-bind", "/lib64", "/lib64"))
        if allow_network:
            command.append("--share-net")
        command.extend(
            (
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                "/tmp",
                "--ro-bind",
                str(manifest.root),
                "/plugin",
                "--chdir",
                "/plugin",
                "/runtime/bin/python",
                f"/plugin/{manifest.entrypoint[0]}",
                *manifest.entrypoint[1:],
            )
        )
        approved_paths: list[str] = []
        for index, permission in enumerate(manifest.permissions):
            if permission.capability is Capability.FILESYSTEM_WRITE:
                raise PetError(
                    ErrorCategory.PERMISSION_DENIED,
                    "plugin.filesystem_write.restricted",
                    "Stable third-party plugins cannot request filesystem writes",
                )
            if permission.capability is not Capability.FILESYSTEM_READ:
                continue
            scope = dict(permission.scope)
            source = Path(scope.get("path", scope.get("directory", ""))).expanduser().resolve()
            if not source.exists():
                raise ValueError("Approved plugin path does not exist")
            destination = f"/approved/{index}"
            # Insert before the executable at the end of the bwrap argument list.
            insert_at = -(1 + len(manifest.entrypoint))
            command[insert_at:insert_at] = [
                "--ro-bind",
                str(source),
                destination,
            ]
            approved_paths.append(destination)
        if approved_paths:
            insert_at = -(1 + len(manifest.entrypoint))
            command[insert_at:insert_at] = [
                "--setenv",
                "VLA_PET_APPROVED_PATHS",
                os.pathsep.join(approved_paths),
            ]
        return command


class PluginHost:
    def __init__(
        self,
        broker: PermissionBroker,
        repository: StateRepository,
        *,
        sandbox: PluginSandbox | None = None,
    ) -> None:
        self.broker = broker
        self.repository = repository
        self.sandbox = sandbox or PluginSandbox()
        self._plugins: dict[str, PluginManifest] = {}
        self._history: dict[str, deque[float]] = {}

    def add(self, manifest: PluginManifest, *, enabled: bool = False) -> None:
        self._plugins[manifest.name] = manifest
        current = self.repository.get_plugin_value("plugin.manager", manifest.name)
        self.repository.set_plugin_value(
            "plugin.manager",
            manifest.name,
            {
                "enabled": bool(current.get("enabled", enabled))
                if isinstance(current, dict)
                else enabled,
                "version": manifest.version,
            },
        )

    def set_enabled(self, name: str, enabled: bool) -> None:
        manifest = self._plugins[name]
        self.repository.set_plugin_value(
            "plugin.manager", name, {"enabled": bool(enabled), "version": manifest.version}
        )

    def enabled(self, name: str) -> bool:
        return bool(self.repository.get_plugin_value("plugin.manager", name, {}).get("enabled", False))

    def manifests(self) -> tuple[PluginManifest, ...]:
        return tuple(self._plugins.values())

    def invoke(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        manifest = self._plugins[name]
        encoded_input = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        if len(encoded_input) > 64 * 1024:
            raise ValueError("Plugin input exceeds 64 KiB")
        if not self.enabled(name):
            raise PetError(ErrorCategory.PERMISSION_DENIED, "plugin.disabled", "Plugin is disabled")
        self.broker.require(Capability.PLUGIN_EXECUTE, subject=f"plugin.{name}")
        for permission in manifest.permissions:
            self.broker.require(
                permission.capability,
                subject=f"plugin.{name}",
                scope=dict(permission.scope),
            )
        self._check_quota(manifest)
        if manifest.runtime == "builtin":
            return self._invoke_builtin(manifest, payload)
        command = self.sandbox.command(
            manifest,
            allow_network=any(item.capability is Capability.NETWORK_HTTP for item in manifest.permissions),
        )
        result = subprocess.run(
            command,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=manifest.timeout_ms / 1000.0,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            check=False,
            preexec_fn=self._resource_limiter(manifest),
        )
        if result.returncode != 0:
            raise RuntimeError(f"Plugin exited with code {result.returncode}")
        if len(result.stdout.encode("utf-8")) > 64 * 1024:
            raise RuntimeError("Plugin output exceeds 64 KiB")
        output = json.loads(result.stdout)
        if not isinstance(output, dict):
            raise RuntimeError("Plugin output must be a JSON object")
        return output

    def _invoke_builtin(
        self, manifest: PluginManifest, payload: dict[str, Any]
    ) -> dict[str, Any]:
        hook = str(payload.get("hook", ""))[:80]
        current = self.repository.get_plugin_value(
            f"plugin.{manifest.name}", "activity", {"invocations": 0}
        )
        invocations = int(current.get("invocations", 0)) + 1 if isinstance(current, dict) else 1
        self.repository.set_plugin_value(
            f"plugin.{manifest.name}",
            "activity",
            {"invocations": invocations, "last_hook": hook},
            quota_bytes=manifest.storage_bytes,
        )
        messages = {
            "timer.started": "Focus Helper is keeping time with you.",
            "timer.completed": "Timer complete — nice work!",
            "focus.completed": "Focus session complete. Time for a gentle break.",
            "pet.interacted": "Companion Care noticed the affection.",
            "item.used": "Companion Care recorded a happy item moment.",
            "daily.completed": "Daily companion activity complete!",
        }
        return {
            "ok": True,
            "plugin": manifest.name,
            "hook": hook,
            "message": messages.get(hook, f"{manifest.display_name} handled {hook}."),
        }

    @staticmethod
    def _resource_limiter(manifest: PluginManifest):
        def limit() -> None:
            import resource

            memory = manifest.max_memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
            cpu_seconds = max(1, int(manifest.timeout_ms / 1000.0) + 1)
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))

        return limit

    def _check_quota(self, manifest: PluginManifest) -> None:
        now = time.monotonic()
        history = self._history.setdefault(manifest.name, deque())
        while history and now - history[0] >= 60.0:
            history.popleft()
        if len(history) >= manifest.max_invocations_per_minute:
            raise PetError(
                ErrorCategory.PERMISSION_DENIED,
                "plugin.quota.exceeded",
                "Plugin invocation quota exceeded",
            )
        history.append(now)
