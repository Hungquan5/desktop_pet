"""Opt-in live smoke test for the visual/action half of the cooperative stack."""

from __future__ import annotations

import argparse
import time

import numpy as np

from vla_pet.contracts import SandboxObservation
from vla_pet.policy import SmolVLMPetPolicy


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model-id",
        default="HuggingFaceTB/SmolVLM2-256M-Video-Instruct",
    )
    parser.add_argument("--quantization", choices=("auto", "int8", "none"), default="auto")
    args = parser.parse_args()
    image = np.full((3, 256, 256), 0.1, dtype=np.float32)
    image[0, 90:220, 90:165] = 0.85
    observation = SandboxObservation(
        sequence_id=1,
        images={"observation.image": image},
        state=(0.7, 1.0, 0.2, 0.0, 1.0, -1.0),
        task="Choose a desktop pet action.",
    )
    started = time.monotonic()
    policy = SmolVLMPetPolicy(
        model_id=args.model_id,
        device="cpu",
        quantization=args.quantization,
    )
    print(
        f"{args.model_id} ({policy.quantization}) loaded in {time.monotonic() - started:.2f}s",
        flush=True,
    )
    started = time.monotonic()
    action = policy.decide(observation)
    print(f"SmolVLM2 action in {time.monotonic() - started:.2f}s: {action.as_dict()}", flush=True)


if __name__ == "__main__":
    main()
