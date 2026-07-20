"""Install or uninstall the wheel and Linux desktop integration for one user/prefix."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import uuid
import venv
from pathlib import Path

CPU_TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
CPU_MODEL_SPECS = ("torch==2.13.0+cpu", "torchvision==0.28.0+cpu")

DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=Momo Desktop Pet
Comment=Local-first SmolVLM and SmolLM desktop companion
Exec={executable}
Icon={icon}
Terminal=false
Categories=Utility;Amusement;
StartupNotify=false
X-GNOME-Autostart-enabled={autostart}
"""


def path_present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def remove_install_pointer(path: Path, release_parent: Path) -> None:
    """Remove a pointer and its managed immutable release, or a legacy directory."""
    if path.is_symlink():
        target = path.resolve(strict=False)
        path.unlink(missing_ok=True)
        if target.parent == release_parent:
            shutil.rmtree(target, ignore_errors=True)
        return
    shutil.rmtree(path, ignore_errors=True)


def clean_orphan_releases(release_parent: Path, pointers: tuple[Path, ...]) -> None:
    """Remove only managed releases that are not referenced by current/previous."""
    retained = {
        pointer.resolve(strict=False)
        for pointer in pointers
        if path_present(pointer)
    }
    if not release_parent.is_dir():
        return
    for release in release_parent.iterdir():
        if release.is_dir() and not release.is_symlink() and release.resolve() not in retained:
            shutil.rmtree(release, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, help="wheel to install")
    parser.add_argument("--prefix", type=Path, default=Path.home() / ".local")
    parser.add_argument("--autostart", action="store_true")
    parser.add_argument(
        "--models",
        action="store_true",
        help="install the optional local SmolLM/SmolVLM/Whisper runtime",
    )
    parser.add_argument(
        "--no-deps",
        action="store_true",
        help="skip dependency installation for offline/package verification",
    )
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="swap the current installation with the previous successful installation",
    )
    parser.add_argument("--delete-data", action="store_true")
    args = parser.parse_args()
    prefix = args.prefix.expanduser().resolve()
    install_root = prefix / "lib" / "vla-pet"
    backup_root = prefix / "lib" / "vla-pet.previous"
    release_parent = prefix / "lib" / "vla-pet-releases"
    environment_root = install_root / "venv"
    executable = prefix / "bin" / "momo-chan"
    compatibility_executable = prefix / "bin" / "vla-pet"
    desktop_path = prefix / "share" / "applications" / "vla-pet.desktop"
    autostart_path = (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        / "autostart"
        / "vla-pet.desktop"
    )

    if args.uninstall:
        remove_install_pointer(install_root, release_parent)
        remove_install_pointer(backup_root, release_parent)
        shutil.rmtree(release_parent, ignore_errors=True)
        executable.unlink(missing_ok=True)
        compatibility_executable.unlink(missing_ok=True)
        desktop_path.unlink(missing_ok=True)
        autostart_path.unlink(missing_ok=True)
        if args.delete_data:
            from vla_pet.paths import AppPaths

            paths = AppPaths.discover()
            for directory in (paths.config, paths.data, paths.cache, paths.state):
                shutil.rmtree(directory, ignore_errors=True)
        print(
            "Uninstalled momo-chan. User data was preserved."
            if not args.delete_data
            else "Uninstalled momo-chan and deleted its user data."
        )
        return 0

    if args.rollback:
        if not path_present(backup_root):
            parser.error("no previous successful installation is available")
        swap_root = prefix / "lib" / f".vla-pet-rollback-{os.getpid()}"
        remove_install_pointer(swap_root, release_parent)
        if path_present(install_root):
            install_root.rename(swap_root)
        try:
            backup_root.rename(install_root)
            if path_present(swap_root):
                swap_root.rename(backup_root)
        except Exception:
            if not path_present(install_root) and path_present(swap_root):
                swap_root.rename(install_root)
            raise
        print("Rolled back momo-chan to the previous successful installation.")
        return 0

    if args.wheel is None or not args.wheel.is_file():
        parser.error("--wheel must name an existing wheel")
    release_root = release_parent / f"release-{uuid.uuid4().hex}"
    release_environment = release_root / "venv"
    release_environment.parent.mkdir(parents=True, exist_ok=True)
    # Each immutable release is isolated from user/system Python packages so a
    # workstation dependency cannot silently change the companion runtime.
    try:
        venv.EnvBuilder(with_pip=True, system_site_packages=False).create(release_environment)
        environment_python = release_environment / "bin" / "python"
        if args.models and not args.no_deps:
            # PyPI's Linux torch wheel may pull a multi-gigabyte CUDA runtime.
            # v1 is CPU-first, so install the matching official CPU wheel first.
            subprocess.run(
                [
                    str(environment_python),
                    "-m",
                    "pip",
                    "install",
                    "--extra-index-url",
                    CPU_TORCH_INDEX,
                    *CPU_MODEL_SPECS,
                ],
                check=True,
            )
        install_command = [str(environment_python), "-m", "pip", "install"]
        if args.no_deps:
            install_command.append("--no-deps")
        package = str(args.wheel.resolve()) + ("[models]" if args.models else "")
        install_command.append(package)
        subprocess.run(install_command, check=True)
    except BaseException:
        shutil.rmtree(release_root, ignore_errors=True)
        raise

    link_root = prefix / "lib" / f".vla-pet-link-{uuid.uuid4().hex}"
    link_root.symlink_to(release_root, target_is_directory=True)
    if path_present(install_root):
        remove_install_pointer(backup_root, release_parent)
        install_root.rename(backup_root)
    elif path_present(backup_root):
        remove_install_pointer(backup_root, release_parent)
    try:
        link_root.rename(install_root)
    except Exception:
        link_root.unlink(missing_ok=True)
        shutil.rmtree(release_root, ignore_errors=True)
        if path_present(backup_root) and not path_present(install_root):
            backup_root.rename(install_root)
        raise
    executable.parent.mkdir(parents=True, exist_ok=True)
    primary_target = environment_root / "bin" / "momo-chan"
    legacy_target = environment_root / "bin" / "vla-pet"
    executable.write_text(
        "#!/bin/sh\n"
        f'target="{primary_target}"\n'
        f'[ -x "$target" ] || target="{legacy_target}"\n'
        'exec "$target" "$@"\n',
        encoding="utf-8",
    )
    executable.chmod(0o755)
    compatibility_executable.write_text(
        f'#!/bin/sh\nexec "{executable}" "$@"\n',
        encoding="utf-8",
    )
    compatibility_executable.chmod(0o755)
    icon = environment_root / "share" / "icons" / "hicolor" / "128x128" / "apps" / "happy.png"
    desktop_path.parent.mkdir(parents=True, exist_ok=True)
    desktop = DESKTOP_ENTRY.format(
        executable=executable,
        icon=icon,
        autostart=str(args.autostart).lower(),
    )
    desktop_path.write_text(desktop, encoding="utf-8")
    if args.autostart:
        autostart_path.parent.mkdir(parents=True, exist_ok=True)
        autostart_path.write_text(desktop, encoding="utf-8")
    else:
        autostart_path.unlink(missing_ok=True)
    clean_orphan_releases(release_parent, (install_root, backup_root))
    print(f"Installed momo-chan into {prefix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
