from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

from vla_pet.persistence import StateRepository

SETTINGS_KEY = "companion.v1"


@dataclass(slots=True)
class CompanionSettings:
    schema_version: int = 1
    onboarding_completed: bool = False
    ai_enabled: bool = True
    memory_enabled: bool = False
    persist_conversation: bool = False
    voice_enabled: bool = False
    tts_enabled: bool = False
    notifications_enabled: bool = False
    active_window_enabled: bool = False
    idle_detection_enabled: bool = False
    system_status_enabled: bool = False
    coding_status_enabled: bool = False
    proactive_enabled: bool = False
    privacy_mode: bool = False
    auto_update_enabled: bool = False
    update_channel: str = "stable"
    update_manifest_url: str = ""
    update_public_key: str = ""
    update_key_id: str = "vla-pet-release"
    quiet_hour_start: int = 22
    quiet_hour_end: int = 8
    denied_applications: list[str] = field(default_factory=list)
    denied_title_fragments: list[str] = field(default_factory=list)
    persona_name: str = ""
    persona_prompt: str = ""

    def __post_init__(self) -> None:
        self.denied_applications = list(self.denied_applications or [])
        self.denied_title_fragments = list(self.denied_title_fragments or [])
        self.update_channel = (
            self.update_channel if self.update_channel in {"stable", "beta", "nightly"} else "stable"
        )
        self.update_manifest_url = self.update_manifest_url.strip()[:2048]
        self.update_public_key = self.update_public_key.strip()[:512]
        self.update_key_id = self.update_key_id.strip()[:120] or "vla-pet-release"
        self.quiet_hour_start = int(self.quiet_hour_start) % 24
        self.quiet_hour_end = int(self.quiet_hour_end) % 24
        self.persona_name = self.persona_name.strip()[:80]
        self.persona_prompt = self.persona_prompt.strip()[:1200]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Any) -> CompanionSettings:
        if not isinstance(value, dict) or int(value.get("schema_version", 0)) != 1:
            return cls()
        names = {item.name for item in fields(cls)}
        return cls(**{key: item for key, item in value.items() if key in names})

    @classmethod
    def load(cls, repository: StateRepository | None) -> CompanionSettings:
        return cls.from_dict(repository.get_setting(SETTINGS_KEY, {})) if repository else cls()

    def save(self, repository: StateRepository | None) -> None:
        if repository is not None:
            repository.set_setting(SETTINGS_KEY, self.as_dict())
