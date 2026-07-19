from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "packaging/vla-pet.desktop",
    "packaging/windows/install.ps1",
    "packaging/macos/install.sh",
    "packaging/flatpak/io.github.vlapet.Companion.yml",
    "packaging/appimage/AppRun",
)


def main() -> int:
    missing = [path for path in REQUIRED if not (ROOT / path).is_file()]
    if missing:
        raise SystemExit(f"Missing packaging contracts: {', '.join(missing)}")
    windows = (ROOT / REQUIRED[1]).read_text(encoding="utf-8")
    macos = (ROOT / REQUIRED[2]).read_text(encoding="utf-8")
    linux = (ROOT / "scripts/install_linux.py").read_text(encoding="utf-8")
    flatpak = (ROOT / REQUIRED[3]).read_text(encoding="utf-8")
    if "current.txt" not in windows or "previous.txt" not in windows:
        raise SystemExit("Windows installer lacks atomic current/previous pointers")
    if "--rollback" not in macos or "previous" not in macos:
        raise SystemExit("macOS installer lacks rollback")
    if "[models]" not in windows or "[models]" not in macos:
        raise SystemExit("Platform installers do not expose the local-model extra")
    cpu_index = "https://download.pytorch.org/whl/cpu"
    if cpu_index not in linux or cpu_index not in windows:
        raise SystemExit("CPU-first installers do not pin the official CPU Torch index")
    if "torchvision==0.28.0+cpu" not in linux or "torchvision==0.28.0+cpu" not in windows:
        raise SystemExit("SmolVLM's torchvision runtime is not CPU-pinned")
    if "org.freedesktop.portal.Desktop" not in flatpak or "--socket=wayland" not in flatpak:
        raise SystemExit("Flatpak manifest lacks Wayland/portal integration")
    print("Validated Linux, Windows, and macOS packaging contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
