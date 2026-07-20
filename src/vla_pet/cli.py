from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import urllib.parse
from collections.abc import Sequence
from pathlib import Path


def _update_source_url(value: str) -> str:
    """Normalize the CLI's documented local-path form to a safe file URL."""
    parsed = urllib.parse.urlparse(value)
    if not parsed.scheme:
        return Path(value).expanduser().resolve().as_uri()
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the SmolVLM + SmolLM anime desktop pet")
    parser.add_argument("--version", action="version", version="momo-chan 1.2.1")
    parser.add_argument("--mock-policy", action="store_true", help="use deterministic actions and template narration")
    parser.add_argument(
        "--safe-mode",
        action="store_true",
        help="disable AI, sensors, persistence writes, and custom character packs",
    )
    parser.add_argument("--offline", action="store_true", help="require already-cached Hugging Face model files")
    parser.add_argument("--debug", action="store_true", help="show state and raw action vectors")
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda", "mps"))
    parser.add_argument(
        "--quantization",
        default="auto",
        choices=("auto", "int8", "none"),
        help="SmolVLM CPU quantization; auto selects INT8 on CPU (default)",
    )
    parser.add_argument(
        "--policy",
        default="vlm",
        choices=("vlm", "vla"),
        help="action policy backend; vlm is the lightweight default",
    )
    parser.add_argument("--model-id", help="override the default model for the selected policy")
    parser.add_argument(
        "--language-model-id",
        default="HuggingFaceTB/SmolLM2-360M-Instruct",
        help="SmolLM checkpoint used for chat and narration",
    )
    parser.add_argument(
        "--language-provider",
        choices=("transformers", "openai-compatible"),
        default="transformers",
        help="local Transformers default or an explicitly configured compatible server",
    )
    parser.add_argument(
        "--language-endpoint",
        default="",
        help="OpenAI-compatible base URL; plain HTTP is accepted only for localhost",
    )
    parser.add_argument(
        "--language-api-key-env",
        default="",
        help="environment variable containing the optional compatible-provider key",
    )
    parser.add_argument(
        "--language-quantization",
        default="none",
        choices=("int8", "none"),
        help="SmolLM quantization; FP32 is the quality-preserving default",
    )
    parser.add_argument("--decision-timeout", type=float, default=180.0)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--assets", type=Path, help="directory containing a character.json manifest")
    parser.add_argument(
        "--sandbox-window",
        action="store_true",
        help="use the original room window instead of the transparent desktop overlay",
    )
    parser.add_argument("--screen-index", type=int, default=0, help="monitor index for the desktop overlay")
    parser.add_argument("--pet-size", type=int, default=128, help="desktop pet height in pixels")
    parser.add_argument(
        "--interaction-padding",
        type=int,
        default=64,
        help="extra clickable padding around the desktop pet in pixels",
    )
    parser.add_argument(
        "--habitat-mode",
        choices=("expanded", "collapsed", "off"),
        default="",
        help="override the saved habitat visibility for this session",
    )
    parser.add_argument("--headless", action="store_true", help="run with SDL's dummy video driver")
    parser.add_argument("--max-seconds", type=float, help="stop automatically; useful for smoke tests")
    parser.add_argument("--no-log", action="store_true", help="disable JSONL session logging")
    parser.add_argument(
        "--persist-conversation",
        action="store_true",
        help="opt in to storing chat turns in the private local SQLite database",
    )
    parser.add_argument(
        "--semantic-interval",
        type=float,
        default=15.0,
        help="minimum seconds between autonomous VLM decisions (default: 15)",
    )
    parser.add_argument(
        "--watch-notifications",
        action="store_true",
        help="opt in to reading desktop notification text and explaining it",
    )
    parser.add_argument("--diagnostics", action="store_true", help="print redacted diagnostics and exit")
    parser.add_argument("--check-update", help="explicit local-file or HTTPS signed update manifest")
    parser.add_argument("--update-public-key", type=Path, help="trusted base64 Ed25519 public key")
    parser.add_argument("--update-key-id", default="vla-pet-release")
    parser.add_argument("--download-update", type=Path, help="download the verified update artifact here")
    parser.add_argument("--export-data", type=Path, help="export private local data to JSON and exit")
    parser.add_argument("--backup-data", type=Path, help="create a private SQLite backup and exit")
    parser.add_argument("--restore-data", type=Path, help="restore a validated SQLite backup and exit")
    parser.add_argument(
        "--clear-conversations",
        action="store_true",
        help="delete persisted conversation turns and exit",
    )
    parser.add_argument(
        "--reset-pet-state",
        action="store_true",
        help="reset persisted needs, mood, and position and exit",
    )
    parser.add_argument(
        "--delete-all-data",
        action="store_true",
        help="permanently delete all momo-chan config, data, cache, and logs",
    )
    parser.add_argument("--skip-onboarding", action="store_true", help="do not show first-launch wizard")
    parser.add_argument(
        "--reset-onboarding",
        action="store_true",
        help="show the guided onboarding again on the next launch",
    )
    parser.add_argument(
        "--stt-command",
        type=Path,
        help="absolute local speech-to-text executable; use --stt-arg {audio} for its WAV input",
    )
    parser.add_argument(
        "--stt-model-id",
        default="openai/whisper-tiny",
        help="lazy local Whisper checkpoint loaded inside the existing AI worker",
    )
    parser.add_argument(
        "--stt-arg",
        action="append",
        default=[],
        help="repeatable speech-to-text argument; {audio} expands to an ephemeral WAV path",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.language_provider == "openai-compatible":
        parsed_endpoint = urllib.parse.urlparse(args.language_endpoint)
        if not args.language_endpoint or parsed_endpoint.scheme not in {"http", "https"}:
            parser.error("--language-provider openai-compatible requires an HTTP(S) endpoint")
        if parsed_endpoint.scheme == "http" and parsed_endpoint.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            parser.error("plain HTTP language providers are restricted to localhost")
    from vla_pet.character import default_character_directory, load_character_or_default
    from vla_pet.paths import AppPaths

    paths = AppPaths.discover()
    os.environ.setdefault("HF_HOME", str(paths.model_cache))
    character_directory = default_character_directory() if args.safe_mode else (
        args.assets or default_character_directory()
    )
    character = load_character_or_default(character_directory).pack

    if args.diagnostics:
        from vla_pet.diagnostics import diagnostics_json

        print(diagnostics_json(paths, character_directory))
        return 0
    if args.check_update:
        if args.update_public_key is None:
            parser.error("--check-update requires --update-public-key")
        from vla_pet.permissions import Capability, PermissionBroker
        from vla_pet.signing import TrustStore
        from vla_pet.updater import SignedUpdateClient

        manifest_url = _update_source_url(args.check_update)
        parsed = urllib.parse.urlparse(manifest_url)
        broker = PermissionBroker()
        broker.grant(
            Capability.UPDATE_CHECK,
            scope={"domain": parsed.hostname or "local-file"},
            reason="explicit CLI update check",
        )
        public_key = base64.b64decode(
            args.update_public_key.expanduser().read_text(encoding="ascii").strip(),
            validate=True,
        )
        client = SignedUpdateClient(broker, TrustStore({args.update_key_id: public_key}))
        update = client.check(manifest_url)
        print(
            json.dumps(
                {
                    "version": update.version,
                    "channel": update.channel,
                    "size_bytes": update.size_bytes,
                    "minimum_database_schema": update.minimum_database_schema,
                },
                indent=2,
            )
        )
        if args.download_update:
            broker.grant(
                Capability.UPDATE_CHECK,
                scope={"domain": urllib.parse.urlparse(update.url).hostname or "local-file"},
                reason="explicit CLI update download",
            )
            print(f"Downloaded verified update to {client.download(update, args.download_update)}")
        return 0
    if args.delete_all_data:
        for directory in (paths.config, paths.data, paths.cache, paths.state):
            shutil.rmtree(directory, ignore_errors=True)
        print("Deleted all momo-chan user data.")
        return 0
    if args.restore_data:
        from vla_pet.persistence import StateRepository

        StateRepository.restore(args.restore_data.expanduser(), paths.database)
        print(f"Restored private data from {args.restore_data.expanduser()}")
        return 0
    if (
        args.export_data
        or args.backup_data
        or args.clear_conversations
        or args.reset_pet_state
        or args.reset_onboarding
    ):
        from vla_pet.persistence import StateRepository
        from vla_pet.settings import CompanionSettings

        with StateRepository(paths.database) as repository:
            if args.clear_conversations:
                repository.clear_conversations()
                print("Persisted conversations cleared.")
            if args.reset_pet_state:
                repository.reset_state()
                print("Persisted pet state reset.")
            if args.export_data:
                destination = repository.export(args.export_data.expanduser())
                print(f"Exported private data to {destination}")
            if args.backup_data:
                destination = repository.backup(args.backup_data.expanduser())
                print(f"Backed up private data to {destination}")
            if args.reset_onboarding:
                settings = CompanionSettings.load(repository)
                settings.onboarding_completed = False
                settings.save(repository)
                print("Onboarding will be shown on the next launch.")
        return 0

    if args.safe_mode:
        args.mock_policy = True
        args.offline = True
        args.watch_notifications = False
        args.persist_conversation = False
        args.assets = None
        args.stt_command = None
        args.stt_arg = []
    if args.headless:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if args.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    from vla_pet.worker import WorkerConfig

    default_model = (
        "HuggingFaceTB/SmolVLM2-256M-Video-Instruct"
        if args.policy == "vlm"
        else "lerobot/smolvla_base"
    )
    worker = WorkerConfig(
        mock_policy=args.mock_policy,
        model_id=args.model_id or default_model,
        language_model_id=args.language_model_id,
        language_quantization=args.language_quantization,
        device=args.device,
        timeout_s=max(1.0, args.decision_timeout),
        offline=args.offline,
        action_mode="sandbox" if args.sandbox_window else "overlay",
        policy_backend=args.policy,
        quantization=args.quantization,
        persona_name=character.persona.name,
        persona_prompt=character.persona.system_prompt,
        stt_model_id=args.stt_model_id,
        language_provider=args.language_provider,
        language_endpoint=args.language_endpoint,
        language_api_key_env=args.language_api_key_env,
    )
    if args.sandbox_window:
        from vla_pet.app import AppConfig, PetSandboxApp

        config = AppConfig(
            worker=worker,
            fps=max(15, min(240, args.fps)),
            debug=args.debug,
            headless=args.headless,
            max_seconds=args.max_seconds,
            logging=not args.no_log,
            asset_directory=args.assets,
        )
        return PetSandboxApp(config).run()

    from vla_pet.overlay import OverlayConfig, run_overlay

    overlay = OverlayConfig(
        worker=worker,
        debug=args.debug,
        screen_index=max(0, args.screen_index),
        pet_size=max(64, min(320, args.pet_size)),
        max_seconds=args.max_seconds,
        logging=not args.no_log,
        asset_directory=args.assets,
        watch_notifications=args.watch_notifications,
        interaction_padding=max(16, min(140, args.interaction_padding)),
        safe_mode=args.safe_mode,
        persist_conversation=args.persist_conversation,
        semantic_interval_s=max(5.0, args.semantic_interval),
        skip_onboarding=args.skip_onboarding or args.headless or args.safe_mode,
        stt_command=(
            (str(args.stt_command.expanduser().resolve()), *tuple(args.stt_arg))
            if args.stt_command
            else ()
        ),
        habitat_mode=args.habitat_mode,
    )
    return run_overlay(overlay)
