from __future__ import annotations

import numpy as np
import pygame

from vla_pet.contracts import SandboxObservation
from vla_pet.world import PetWorld

TASK_PROMPT = "Move around your room, play with the toy, and express how you feel."


def surface_to_chw(surface: pygame.Surface, size: int = 256) -> np.ndarray:
    resized = pygame.transform.smoothscale(surface, (size, size))
    pixels = pygame.surfarray.array3d(resized)
    hwc = np.transpose(pixels, (1, 0, 2))
    return np.ascontiguousarray(np.transpose(hwc, (2, 0, 1)), dtype=np.float32) / 255.0


def _square_crop(surface: pygame.Surface, cx: float, cy: float, span: int = 280) -> pygame.Surface:
    width, height = surface.get_size()
    half = span // 2
    left = max(0, min(width - span, int(cx) - half)) if width >= span else 0
    top = max(0, min(height - span, int(cy) - half)) if height >= span else 0
    rect = pygame.Rect(left, top, min(span, width), min(span, height))
    return surface.subsurface(rect).copy()


def build_observation(surface: pygame.Surface, world: PetWorld) -> SandboxObservation:
    avatar_crop = _square_crop(
        surface,
        world.x + world.PET_WIDTH / 2,
        world.y + world.PET_HEIGHT / 2,
    )
    toy_crop = _square_crop(surface, world.toy.x, world.toy.y)
    observation = SandboxObservation(
        sequence_id=world.sequence_id,
        images={
            "observation.image": surface_to_chw(surface),
            "observation.image2": surface_to_chw(avatar_crop),
            "observation.image3": surface_to_chw(toy_crop),
        },
        state=world.normalized_state(),
        task=TASK_PROMPT,
    )
    observation.validate()
    return observation

