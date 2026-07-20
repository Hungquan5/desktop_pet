"""Deterministically inspect and import a built Momo Chan wheel."""

from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REQUIRED_SUFFIXES = {
    "vla_pet/cli.py",
    "vla_pet/overlay.py",
    "vla_pet/life.py",
    "vla_pet/events.py",
    "vla_pet/permissions.py",
    "vla_pet/persistence.py",
    "vla_pet/habitat.py",
    "vla_pet/growth.py",
    "vla_pet/companion_panel.py",
    "vla_pet/platform_adapters.py",
    "vla_pet/memory.py",
    "vla_pet/tool_runtime.py",
    "vla_pet/async_tools.py",
    "vla_pet/voice.py",
    "vla_pet/plugin_dispatcher.py",
    "vla_pet/plugins.py",
    "vla_pet/update_service.py",
    "vla_pet/updater.py",
    "share/vla-pet/animations/character.json",
    "share/vla-pet/animations/PROVENANCE.md",
    "share/vla-pet/animations/frames/baby/frame_00.png",
    "share/vla-pet/animations/frames/child/frame_15.png",
    "share/vla-pet/animations/frames/teen/frame_15.png",
    "share/vla-pet/animations/frames/evolution/frame_03.png",
    "share/vla-pet/sounds/momo_pop.wav",
    "share/vla-pet/characters/orbit/character.json",
    "share/vla-pet/plugins/focus-helper/plugin.json",
    "share/vla-pet/plugins/companion-care/plugin.json",
    "share/applications/vla-pet.desktop",
    "share/doc/vla-pet/plugin-spec-v1.md",
    "share/doc/vla-pet/character-pack-spec-v2.md",
    "share/doc/vla-pet/character-pack-spec-v3.md",
    "share/doc/vla-pet/character-pack-spec-v4.md",
    "share/doc/vla-pet/feature-audit-v1.2.md",
    "share/doc/vla-pet/release-evidence-v1.2.md",
}


def resolve_artifact(pattern: str) -> Path:
    matches = [Path(path) for path in glob.glob(pattern)]
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly one wheel for {pattern!r}, found {len(matches)}")
    return matches[0].resolve()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True, help="wheel path or glob")
    args = parser.parse_args()
    artifact = resolve_artifact(args.artifact)
    if artifact.suffix != ".whl":
        raise SystemExit(f"Not a wheel: {artifact}")

    with zipfile.ZipFile(artifact) as wheel:
        names = set(wheel.namelist())
        entry_point_files = [
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        ]
        if len(entry_point_files) != 1:
            raise SystemExit("Wheel must contain exactly one entry_points.txt")
        entry_points = wheel.read(entry_point_files[0]).decode("utf-8")
    missing = sorted(
        suffix for suffix in REQUIRED_SUFFIXES if not any(name.endswith(suffix) for name in names)
    )
    if missing:
        raise SystemExit(f"Wheel is missing required content: {', '.join(missing)}")
    expected_commands = {
        "momo-chan = vla_pet.cli:main",
        "vla-pet = vla_pet.cli:main",
    }
    missing_commands = sorted(command for command in expected_commands if command not in entry_points)
    if missing_commands:
        raise SystemExit(f"Wheel is missing console commands: {', '.join(missing_commands)}")

    with tempfile.TemporaryDirectory(prefix="vla-pet-wheel-") as temporary:
        target = Path(temporary) / "site"
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(target), str(artifact)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(target)
        result = subprocess.run(
            [sys.executable, "-m", "vla_pet", "--version"],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        if "1.2.1" not in result.stdout:
            raise SystemExit(f"Unexpected installed version: {result.stdout.strip()}")

    print(f"Verified release artifact: {artifact.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
