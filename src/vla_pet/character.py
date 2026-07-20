from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vla_pet.contracts import ActionKind
from vla_pet.errors import ErrorCategory, PetError


def default_character_directory() -> Path:
    source_assets = Path(__file__).resolve().parents[2] / "animations" / "momo_v2"
    installed_assets = Path(sys.prefix) / "share" / "vla-pet" / "animations"
    return source_assets if source_assets.exists() else installed_assets


@dataclass(frozen=True, slots=True)
class AnimationSpec:
    name: str
    frames: tuple[Path, ...]
    fps: float
    loop: bool
    priority: int


@dataclass(frozen=True, slots=True)
class PersonaSpec:
    name: str
    system_prompt: str
    greeting: str
    traits: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VoiceSpec:
    provider: str = "qt-speechd"
    voice_id: str = ""
    rate: float = 0.0
    pitch: float = 0.0


@dataclass(frozen=True, slots=True)
class CharacterPack:
    schema_version: int
    character_id: str
    display_name: str
    root: Path
    canvas_size: tuple[int, int]
    default_scale: float
    license: str
    animations: dict[ActionKind, AnimationSpec]
    persona: PersonaSpec
    voice: VoiceSpec
    hitbox_padding: int = 64
    alpha_threshold: int = 8
    emotion_map: tuple[tuple[str, str], ...] = ()
    attribution: tuple[tuple[str, str], ...] = ()
    pack_version: str = "1.0.0"
    expressive_animations: dict[str, AnimationSpec] = field(default_factory=dict)
    ui_accent: str = "#B9362E"
    sound_attribution: tuple[tuple[str, str], ...] = ()

    _ROLE_FALLBACKS = {
        "fall": ActionKind.JUMP,
        "held": ActionKind.JUMP,
        "landing": ActionKind.IDLE,
        "eat": ActionKind.HAPPY,
        "play": ActionKind.THROW,
        "sleep": ActionKind.IDLE,
        "box": ActionKind.IDLE,
        "think": ActionKind.IDLE,
        "listen": ActionKind.IDLE,
        "talk": ActionKind.HAPPY,
    }

    def animation_for(self, role: str | ActionKind) -> AnimationSpec:
        name = role.value if isinstance(role, ActionKind) else str(role).strip().lower()
        if name in self.expressive_animations:
            return self.expressive_animations[name]
        try:
            return self.animations[ActionKind(name)]
        except ValueError:
            return self.animations[self._ROLE_FALLBACKS.get(name, ActionKind.IDLE)]

    @classmethod
    def load(cls, directory: Path) -> CharacterPack:
        root = directory.expanduser().resolve()
        manifest_path = root / "character.json"
        try:
            raw: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PetError(
                ErrorCategory.CHARACTER_PACK,
                "character.manifest.unreadable",
                f"Cannot read character manifest {manifest_path}: {exc}",
            ) from exc

        schema_version = int(raw.get("schema_version", 0))
        if schema_version not in {1, 2, 3}:
            raise PetError(
                ErrorCategory.CHARACTER_PACK,
                "character.schema.unsupported",
                f"Unsupported character schema: {raw.get('schema_version')!r}",
            )
        character_id = str(raw.get("id", "")).strip()
        if not character_id or not character_id.replace("-", "").replace("_", "").isalnum():
            raise PetError(ErrorCategory.CHARACTER_PACK, "character.id.invalid", "Invalid character id")

        canvas = raw.get("canvas_size", [128, 128])
        if not isinstance(canvas, list) or len(canvas) != 2 or not all(
            isinstance(value, int) and value > 0 for value in canvas
        ):
            raise PetError(
                ErrorCategory.CHARACTER_PACK,
                "character.canvas.invalid",
                "canvas_size must contain two positive integers",
            )

        specs: dict[ActionKind, AnimationSpec] = {}
        animations = raw.get("animations")
        if not isinstance(animations, dict):
            raise PetError(
                ErrorCategory.CHARACTER_PACK,
                "character.animations.missing",
                "Character manifest has no animations object",
            )
        for kind in ActionKind:
            value = animations.get(kind.value)
            if not isinstance(value, dict):
                raise PetError(
                    ErrorCategory.CHARACTER_PACK,
                    "character.animation.missing",
                    f"Missing required animation: {kind.value}",
                )
            frames = cls._resolve_frames(root, value.get("frames"), kind)
            fps = float(value.get("fps", 8.0))
            if not 0.1 <= fps <= 120.0:
                raise PetError(
                    ErrorCategory.CHARACTER_PACK,
                    "character.animation.fps",
                    f"Invalid FPS for {kind.value}: {fps}",
                )
            specs[kind] = AnimationSpec(
                kind.value,
                frames,
                fps,
                bool(value.get("loop", True)),
                int(value.get("priority", 0)),
            )
        expressive_specs: dict[str, AnimationSpec] = {}
        if schema_version >= 3:
            for role, value in animations.items():
                name = str(role).strip().lower()
                if name in {kind.value for kind in ActionKind}:
                    continue
                if not name or not isinstance(value, dict):
                    raise PetError(
                        ErrorCategory.CHARACTER_PACK,
                        "character.animation.invalid",
                        f"Invalid expressive animation: {role}",
                    )
                frames = cls._resolve_frames(root, value.get("frames"), name)
                fps = float(value.get("fps", 8.0))
                if not 0.1 <= fps <= 120.0:
                    raise PetError(
                        ErrorCategory.CHARACTER_PACK,
                        "character.animation.fps",
                        f"Invalid FPS for {name}: {fps}",
                    )
                expressive_specs[name] = AnimationSpec(
                    name,
                    frames,
                    fps,
                    bool(value.get("loop", True)),
                    int(value.get("priority", 0)),
                )

        persona_raw = raw.get("persona", {})
        voice_raw = raw.get("voice", {})
        hitbox_raw = raw.get("hitbox", {})
        attribution_raw = raw.get("attribution", {})
        emotion_raw = raw.get("emotion_map", {})
        ui_raw = raw.get("ui", {})
        sound_raw = raw.get("sound_attribution", {})
        if not all(
            isinstance(value, dict)
            for value in (
                persona_raw,
                voice_raw,
                hitbox_raw,
                attribution_raw,
                emotion_raw,
                ui_raw,
                sound_raw,
            )
        ):
            raise PetError(
                ErrorCategory.CHARACTER_PACK,
                "character.metadata.invalid",
                "Persona, voice, hitbox, emotion, and attribution metadata must be objects",
            )
        license_name = str(raw.get("license", "UNSPECIFIED")).strip()
        if schema_version >= 2 and not license_name:
            raise PetError(
                ErrorCategory.CHARACTER_PACK,
                "character.license.missing",
                "v2 character packs must declare a license",
            )
        persona_name = str(persona_raw.get("name", raw.get("display_name", character_id))).strip()
        system_prompt = str(persona_raw.get("system_prompt", "")).strip()
        if schema_version >= 2 and (not persona_name or not system_prompt):
            raise PetError(
                ErrorCategory.CHARACTER_PACK,
                "character.persona.missing",
                "v2 character packs must declare persona name and system_prompt",
            )
        return cls(
            schema_version=schema_version,
            character_id=character_id,
            display_name=str(raw.get("display_name", character_id)).strip() or character_id,
            root=root,
            canvas_size=(canvas[0], canvas[1]),
            default_scale=float(raw.get("default_scale", 1.0)),
            license=license_name,
            animations=specs,
            persona=PersonaSpec(
                persona_name or character_id,
                system_prompt
                or "You are a warm and playful tiny desktop pet. Reply directly and concisely.",
                str(persona_raw.get("greeting", "Hello!"))[:240],
                tuple(str(item) for item in persona_raw.get("traits", []) if str(item).strip()),
            ),
            voice=VoiceSpec(
                str(voice_raw.get("provider", "qt-speechd")),
                str(voice_raw.get("voice_id", "")),
                min(1.0, max(-1.0, float(voice_raw.get("rate", 0.0)))),
                min(1.0, max(-1.0, float(voice_raw.get("pitch", 0.0)))),
            ),
            hitbox_padding=max(0, min(160, int(hitbox_raw.get("padding", 64)))),
            alpha_threshold=max(0, min(255, int(hitbox_raw.get("alpha_threshold", 8)))),
            emotion_map=tuple(sorted((str(key), str(value)) for key, value in emotion_raw.items())),
            attribution=tuple(
                sorted((str(key), str(value)) for key, value in attribution_raw.items())
            ),
            pack_version=str(raw.get("version", "1.0.0")).strip()[:40] or "1.0.0",
            expressive_animations=expressive_specs,
            ui_accent=str(ui_raw.get("accent", "#B9362E"))[:20],
            sound_attribution=tuple(
                sorted((str(key), str(value)) for key, value in sound_raw.items())
            ),
        )

    @staticmethod
    def _resolve_frames(root: Path, value: Any, kind: ActionKind | str) -> tuple[Path, ...]:
        name = kind.value if isinstance(kind, ActionKind) else str(kind)
        patterns = [value] if isinstance(value, str) else value
        if not isinstance(patterns, list) or not patterns or not all(
            isinstance(pattern, str) and pattern for pattern in patterns
        ):
            raise PetError(
                ErrorCategory.CHARACTER_PACK,
                "character.frames.invalid",
                f"Animation {name} must declare one or more frames",
            )
        frames: list[Path] = []
        for pattern in patterns:
            if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
                raise PetError(
                    ErrorCategory.CHARACTER_PACK,
                    "character.frames.unsafe_path",
                    f"Unsafe frame path in {name}",
                )
            matches = sorted(root.glob(pattern))
            for match in matches:
                resolved = match.resolve()
                if resolved.is_file() and resolved.is_relative_to(root):
                    frames.append(resolved)
        if not frames:
            raise PetError(
                ErrorCategory.CHARACTER_PACK,
                "character.frames.missing",
                f"No frames found for {name}",
            )
        return tuple(frames)


@dataclass(frozen=True, slots=True)
class CharacterLoadResult:
    pack: CharacterPack
    fallback_error_code: str = ""


def load_character_or_default(directory: Path | None) -> CharacterLoadResult:
    """Load a custom pack, falling back only when the custom pack is invalid."""
    default_directory = default_character_directory()
    if directory is None:
        return CharacterLoadResult(CharacterPack.load(default_directory))
    try:
        return CharacterLoadResult(CharacterPack.load(directory))
    except PetError as exc:
        return CharacterLoadResult(
            CharacterPack.load(default_directory),
            fallback_error_code=exc.code,
        )
