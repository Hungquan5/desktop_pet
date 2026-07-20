"""Run the deterministic end-to-end v1.2 verification pipeline."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(
    label: str,
    command: list[str],
    *,
    environment: dict[str, str] | None = None,
    reject_output: tuple[str, ...] = (),
) -> None:
    print(f"[verify] {label}", flush=True)
    if not reject_output:
        subprocess.run(command, cwd=ROOT, env=environment, check=True)
        return
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    combined = result.stdout + result.stderr
    found = next((token for token in reject_output if token in combined), "")
    if found:
        raise SystemExit(f"{label} emitted forbidden runtime output: {found}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--with-models",
        action="store_true",
        help="also run the slow cached SmolVLM + SmolLM cooperation smoke",
    )
    parser.add_argument(
        "--with-performance",
        action="store_true",
        help="also run the five-minute idle CPU acceptance gate",
    )
    parser.add_argument(
        "--with-voice-model",
        action="store_true",
        help="also run the cached lazy Whisper provider smoke",
    )
    args = parser.parse_args()
    python = sys.executable

    run("lint", [python, "-m", "ruff", "check", "src", "tests", "scripts"])
    run("compile", [python, "-m", "compileall", "-q", "src", "scripts"])
    run(
        "tests and coverage",
        [python, "-m", "pytest", "--cov=vla_pet", "--cov-report=term-missing", "-q"],
    )
    run("build", [python, "-m", "build", "--no-isolation"])
    run(
        "wheel contents and isolated import",
        [python, "scripts/verify_release.py", "--artifact", "dist/*-1.2.1-*.whl"],
    )
    run("10k memory retrieval budget", [python, "scripts/measure_memory.py"])
    run("cross-platform packaging contracts", [python, "scripts/verify_packaging.py"])

    with tempfile.TemporaryDirectory(prefix="vla-pet-e2e-") as temporary:
        temp = Path(temporary)
        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(temp / "home"),
                "XDG_CONFIG_HOME": str(temp / "config"),
                "XDG_DATA_HOME": str(temp / "data"),
                "XDG_CACHE_HOME": str(temp / "cache"),
                "XDG_STATE_HOME": str(temp / "state"),
                "QT_QPA_PLATFORM": "offscreen",
                "SDL_VIDEODRIVER": "dummy",
                "SDL_AUDIODRIVER": "dummy",
            }
        )
        started = time.monotonic()
        run(
            "headless safe-mode overlay",
            [
                python,
                "-m",
                "vla_pet",
                "--safe-mode",
                "--headless",
                "--screen-index",
                "99",
                "--max-seconds",
                "3",
                "--no-log",
            ],
            environment=environment,
            reject_output=("Traceback", "AttributeError", "RuntimeError"),
        )
        print(f"[verify] overlay elapsed={time.monotonic() - started:.2f}s", flush=True)

        prefix = temp / "prefix"
        run(
            "create v1 private data",
            [python, "-m", "vla_pet", "--reset-pet-state"],
            environment=environment,
        )
        backup = temp / "backup" / "pet.db"
        run(
            "backup v1 private data",
            [python, "-m", "vla_pet", "--backup-data", str(backup)],
            environment=environment,
        )
        run(
            "restore v1 private data",
            [python, "-m", "vla_pet", "--restore-data", str(backup)],
            environment=environment,
        )
        wheels = tuple((ROOT / "dist").glob("*-1.2.1-*.whl"))
        if len(wheels) != 1:
            raise SystemExit(f"Expected one v1.2.1 wheel, found {len(wheels)}")
        wheel = wheels[0]
        run(
            "temporary-prefix install",
            [
                python,
                "scripts/install_linux.py",
                "--wheel",
                str(wheel),
                "--prefix",
                str(prefix),
                "--no-deps",
            ],
            environment=environment,
        )
        run(
            "installed launcher",
            [str(prefix / "bin" / "momo-chan"), "--version"],
            environment=environment,
        )
        run(
            "compatibility launcher",
            [str(prefix / "bin" / "vla-pet"), "--version"],
            environment=environment,
        )
        desktop = prefix / "share" / "applications" / "vla-pet.desktop"
        icon_line = next(
            (line for line in desktop.read_text(encoding="utf-8").splitlines() if line.startswith("Icon=")),
            "",
        )
        if not icon_line or not Path(icon_line.removeprefix("Icon=")).is_file():
            raise SystemExit("Installed desktop launcher references a missing icon")
        run(
            "atomic upgrade",
            [
                python,
                "scripts/install_linux.py",
                "--wheel",
                str(wheel),
                "--prefix",
                str(prefix),
                "--no-deps",
            ],
            environment=environment,
        )
        run(
            "rollback to previous install",
            [python, "scripts/install_linux.py", "--prefix", str(prefix), "--rollback"],
            environment=environment,
        )
        run(
            "rolled-back launcher",
            [str(prefix / "bin" / "momo-chan"), "--version"],
            environment=environment,
        )
        run(
            "clean uninstall",
            [python, "scripts/install_linux.py", "--prefix", str(prefix), "--uninstall"],
            environment=environment,
        )
        leftover_launchers = [
            launcher
            for launcher in (prefix / "bin" / "momo-chan", prefix / "bin" / "vla-pet")
            if launcher.exists()
        ]
        if leftover_launchers:
            raise SystemExit(f"Uninstall left launchers behind: {leftover_launchers}")

    if args.with_models:
        environment = os.environ.copy()
        environment.update(
            {
                "HF_HOME": str(ROOT / ".cache" / "huggingface"),
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
            }
        )
        run("cached SmolVLM + SmolLM cooperation", [python, "scripts/smoke_coop.py"], environment=environment)

    if args.with_performance:
        run(
            "five-minute expanded-habitat CPU gate",
            [
                python,
                "scripts/measure_idle_cpu.py",
                "--seconds",
                "300",
                "--habitat-mode",
                "expanded",
                "--max-cpu-percent",
                "5",
            ],
        )
        run(
            "five-minute collapsed-habitat CPU gate",
            [
                python,
                "scripts/measure_idle_cpu.py",
                "--seconds",
                "300",
                "--habitat-mode",
                "collapsed",
                "--max-cpu-percent",
                "3",
            ],
        )

    if args.with_voice_model:
        environment = os.environ.copy()
        environment.update(
            {
                "HF_HOME": str(ROOT / ".cache" / "huggingface"),
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
            }
        )
        run("cached local Whisper smoke", [python, "scripts/smoke_voice.py"], environment=environment)

    print("[verify] all selected v1.2 gates passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
