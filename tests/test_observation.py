import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np
import pygame

from vla_pet.observation import build_observation
from vla_pet.world import PetWorld


def test_builds_checkpoint_compatible_observation() -> None:
    pygame.init()
    surface = pygame.Surface((PetWorld.WIDTH, PetWorld.HEIGHT))
    surface.fill((12, 34, 56))
    observation = build_observation(surface, PetWorld())

    observation.validate()
    assert len(observation.images) == 3
    assert all(image.shape == (3, 256, 256) for image in observation.images.values())
    assert all(image.dtype == np.float32 for image in observation.images.values())
    assert len(observation.state) == 6
    pygame.quit()

