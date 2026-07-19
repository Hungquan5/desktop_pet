from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

APP_ID = "vla-pet"


def ensure_private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


@dataclass(frozen=True, slots=True)
class AppPaths:
    config: Path
    data: Path
    cache: Path
    state: Path

    @classmethod
    def discover(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        home: Path | None = None,
        platform_name: str | None = None,
    ) -> AppPaths:
        values = os.environ if env is None else env
        user_home = Path(values.get("HOME", str(home or Path.home()))).expanduser()
        platform_value = platform_name or sys.platform

        if not any(name in values for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME")):
            if platform_value.startswith("win"):
                roaming = Path(
                    values.get("APPDATA", str(user_home / "AppData" / "Roaming"))
                ).expanduser()
                local = Path(
                    values.get("LOCALAPPDATA", str(user_home / "AppData" / "Local"))
                ).expanduser()
                return cls(
                    config=roaming / APP_ID,
                    data=roaming / APP_ID,
                    cache=local / APP_ID / "cache",
                    state=local / APP_ID / "state",
                )
            if platform_value == "darwin":
                library = user_home / "Library"
                return cls(
                    config=library / "Preferences" / APP_ID,
                    data=library / "Application Support" / APP_ID,
                    cache=library / "Caches" / APP_ID,
                    state=library / "Logs" / APP_ID,
                )

        def xdg(name: str, fallback: str) -> Path:
            return Path(values.get(name, str(user_home / fallback))).expanduser() / APP_ID

        return cls(
            config=xdg("XDG_CONFIG_HOME", ".config"),
            data=xdg("XDG_DATA_HOME", ".local/share"),
            cache=xdg("XDG_CACHE_HOME", ".cache"),
            state=xdg("XDG_STATE_HOME", ".local/state"),
        )

    def ensure(self) -> AppPaths:
        for directory in (self.config, self.data, self.cache, self.state):
            ensure_private_directory(directory)
        return self

    @property
    def database(self) -> Path:
        return self.data / "pet.db"

    @property
    def log_directory(self) -> Path:
        return self.state / "logs"

    @property
    def model_cache(self) -> Path:
        explicit = os.environ.get("HF_HOME")
        if explicit:
            return Path(explicit).expanduser()
        development_cache = Path.cwd() / ".cache" / "huggingface"
        return development_cache if development_cache.exists() else self.cache / "huggingface"
