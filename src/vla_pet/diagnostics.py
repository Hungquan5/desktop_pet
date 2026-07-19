from __future__ import annotations

import json
import os
import platform
import shutil
import sqlite3
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

from vla_pet.character import CharacterPack
from vla_pet.paths import AppPaths
from vla_pet.persistence import SCHEMA_VERSION
from vla_pet.plugins import PluginManifest, default_plugin_directory


def collect_diagnostics(paths: AppPaths, character_directory: Path) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    try:
        pack = CharacterPack.load(character_directory)
        checks["character_pack"] = {"ok": True, "id": pack.character_id}
    except Exception as exc:
        checks["character_pack"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    for name, directory in (
        ("config_directory", paths.config),
        ("data_directory", paths.data),
        ("cache_directory", paths.cache),
        ("state_directory", paths.state),
    ):
        existing = directory if directory.exists() else directory.parent
        checks[name] = {"path": str(directory), "writable": os.access(existing, os.W_OK)}

    if paths.database.exists():
        try:
            database = sqlite3.connect(f"file:{paths.database}?mode=ro", uri=True)
            checks["database"] = {
                "ok": database.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
                "schema": int(database.execute("PRAGMA user_version").fetchone()[0]),
                "supported_schema": SCHEMA_VERSION,
            }
            database.close()
        except sqlite3.Error as exc:
            checks["database"] = {"ok": False, "error": type(exc).__name__}
    try:
        memory_db = sqlite3.connect(":memory:")
        memory_db.execute("CREATE VIRTUAL TABLE test_fts USING fts5(value)")
        memory_db.close()
        checks["sqlite_fts5"] = {"ok": True}
    except sqlite3.Error:
        checks["sqlite_fts5"] = {"ok": False}

    plugin_root = default_plugin_directory().resolve()
    plugin_results: list[dict[str, Any]] = []
    if plugin_root.is_dir():
        for directory in sorted(plugin_root.iterdir()):
            if not directory.is_dir():
                continue
            try:
                manifest = PluginManifest.load(directory, trusted_builtin_root=plugin_root)
                plugin_results.append({"name": manifest.name, "ok": True})
            except Exception as exc:
                plugin_results.append({"name": directory.name, "ok": False, "error": type(exc).__name__})
    checks["bundled_plugins"] = {
        "ok": bool(plugin_results) and all(item["ok"] for item in plugin_results),
        "plugins": plugin_results,
    }

    packages = {}
    for package in ("cryptography", "numpy", "pygame-ce", "PySide6", "torch", "transformers"):
        try:
            packages[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            packages[package] = None

    report = {
        "application": "vla-pet",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "display": {
            "wayland": bool(os.environ.get("WAYLAND_DISPLAY")),
            "x11": bool(os.environ.get("DISPLAY")),
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
        },
        "packages": packages,
        "model_cache": {"path": str(paths.model_cache), "exists": paths.model_cache.exists()},
        "voice": {
            "capture": shutil.which("arecord") or "",
            "external_stt": shutil.which("whisper-cli") or "",
            "worker_stt_model": "openai/whisper-tiny",
        },
        "plugin_sandbox": {"bubblewrap": shutil.which("bwrap") or ""},
        "checks": checks,
    }
    report["ok"] = all(
        value.get("ok", value.get("writable", True)) for value in checks.values()
    )
    return report


def diagnostics_json(paths: AppPaths, character_directory: Path) -> str:
    return json.dumps(collect_diagnostics(paths, character_directory), indent=2, sort_keys=True)
