"""Measure aggregate CPU usage of the headless pet process tree."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def process_ticks(pid: int) -> int | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
        return int(fields[13]) + int(fields[14])
    except (FileNotFoundError, IndexError, PermissionError, ValueError):
        return None


def descendants(root_pid: int) -> set[int]:
    found = {root_pid}
    pending = [root_pid]
    while pending:
        pid = pending.pop()
        try:
            raw = Path(f"/proc/{pid}/task/{pid}/children").read_text(encoding="utf-8")
        except (FileNotFoundError, PermissionError):
            continue
        for value in raw.split():
            child = int(value)
            if child not in found:
                found.add(child)
                pending.append(child)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=300.0)
    parser.add_argument("--max-cpu-percent", type=float, default=3.0)
    args = parser.parse_args()
    seconds = max(5.0, args.seconds)

    with tempfile.TemporaryDirectory(prefix="vla-pet-cpu-") as temporary:
        environment = os.environ.copy()
        temp = Path(temporary)
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
        command = [
            sys.executable,
            "-m",
            "vla_pet",
            "--safe-mode",
            "--headless",
            "--screen-index",
            "98",
            "--max-seconds",
            str(seconds),
            "--no-log",
        ]
        started = time.monotonic()
        process = subprocess.Popen(
            command,
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        baseline: dict[int, int] = {}
        latest: dict[int, int] = {}
        while process.poll() is None:
            for pid in descendants(process.pid):
                ticks = process_ticks(pid)
                if ticks is None:
                    continue
                baseline.setdefault(pid, ticks)
                latest[pid] = ticks
            time.sleep(0.25)
        elapsed = time.monotonic() - started
        if process.returncode != 0:
            raise SystemExit(f"Headless pet exited with status {process.returncode}")

    clock_ticks = os.sysconf("SC_CLK_TCK")
    cpu_seconds = sum(max(0, latest[pid] - start) for pid, start in baseline.items()) / clock_ticks
    cpu_percent = (cpu_seconds / elapsed) * 100.0
    print(
        f"idle_cpu_percent={cpu_percent:.2f} cpu_seconds={cpu_seconds:.2f} "
        f"wall_seconds={elapsed:.2f} processes={len(baseline)}"
    )
    if cpu_percent > args.max_cpu_percent:
        raise SystemExit(
            f"Idle CPU {cpu_percent:.2f}% exceeds {args.max_cpu_percent:.2f}% of one core"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
