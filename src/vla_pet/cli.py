from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the SmolVLM + SmolLM anime desktop pet")
    parser.add_argument("--mock-policy", action="store_true", help="use deterministic actions and template narration")
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
        "--language-quantization",
        default="none",
        choices=("int8", "none"),
        help="SmolLM quantization; FP32 is the quality-preserving default",
    )
    parser.add_argument("--decision-timeout", type=float, default=180.0)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--assets", type=Path, help="directory containing the six avatar PNG files")
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
    parser.add_argument("--headless", action="store_true", help="run with SDL's dummy video driver")
    parser.add_argument("--max-seconds", type=float, help="stop automatically; useful for smoke tests")
    parser.add_argument("--no-log", action="store_true", help="disable JSONL session logging")
    parser.add_argument(
        "--watch-notifications",
        action="store_true",
        help="opt in to reading desktop notification text and explaining it",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
    )
    return run_overlay(overlay)
