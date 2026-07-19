from __future__ import annotations

import math
import textwrap
from pathlib import Path

import pygame

from vla_pet.contracts import ActionKind
from vla_pet.world import PetWorld


POSE_FILES = {
    ActionKind.IDLE: "idle.png",
    ActionKind.WALK: "walking.png",
    ActionKind.JUMP: "jumping.png",
    ActionKind.THROW: "throw.png",
    ActionKind.HAPPY: "happy.png",
    ActionKind.SAD: "sad.png",
}


def default_asset_directory() -> Path:
    repository_root = Path(__file__).resolve().parents[2]
    return repository_root / "animations"


class Renderer:
    def __init__(self, asset_directory: Path | None = None) -> None:
        self.asset_directory = asset_directory or default_asset_directory()
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 19)
        self.title_font = pygame.font.Font(None, 29)
        self.sprites = self._load_sprites()

    def _load_sprites(self) -> dict[ActionKind, pygame.Surface]:
        sprites: dict[ActionKind, pygame.Surface] = {}
        for kind, filename in POSE_FILES.items():
            path = self.asset_directory / filename
            if not path.exists():
                raise FileNotFoundError(f"Missing avatar asset: {path}")
            sprites[kind] = pygame.image.load(path).convert_alpha()
        return sprites

    def draw_world(self, surface: pygame.Surface, world: PetWorld, elapsed: float) -> None:
        surface.fill((28, 35, 54))
        pygame.draw.circle(surface, (80, 92, 125), (800, 90), 45)
        pygame.draw.circle(surface, (37, 47, 70), (800, 90), 34)
        for x in range(50, world.WIDTH, 120):
            pygame.draw.circle(surface, (215, 208, 168), (x, 75 + (x % 3) * 15), 2)

        pygame.draw.rect(surface, (62, 72, 93), (0, 390, world.WIDTH, 76))
        pygame.draw.rect(surface, (83, 69, 67), (0, int(world.FLOOR_Y), world.WIDTH, 74))
        for x in range(0, world.WIDTH, 80):
            pygame.draw.line(surface, (101, 83, 78), (x, int(world.FLOOR_Y)), (x + 25, world.HEIGHT), 2)

        self._draw_toy(surface, world)
        self._draw_pet(surface, world, elapsed)

    def _draw_toy(self, surface: pygame.Surface, world: PetWorld) -> None:
        center = (int(world.toy.x), int(world.toy.y))
        pygame.draw.circle(surface, (32, 37, 48), (center[0] + 4, int(world.FLOOR_Y) + 3), 17, 0)
        pygame.draw.circle(surface, (92, 196, 210), center, int(world.toy.radius))
        pygame.draw.circle(surface, (192, 248, 241), (center[0] - 5, center[1] - 5), 5)

    def _draw_pet(self, surface: pygame.Surface, world: PetWorld, elapsed: float) -> None:
        sprite = self.sprites[world.pose]
        target_height = 136 if world.pose is ActionKind.THROW else 124
        scale = target_height / sprite.get_height()
        target_width = max(1, int(sprite.get_width() * scale))
        image = pygame.transform.smoothscale(sprite, (target_width, target_height))
        if world.facing < 0:
            image = pygame.transform.flip(image, True, False)

        bob = 0
        if world.pose is ActionKind.IDLE:
            bob = int(math.sin(elapsed * 3.0) * 2)
        elif world.pose is ActionKind.HAPPY:
            bob = -int(abs(math.sin(elapsed * 9.0)) * 7)

        x = int(world.x + world.PET_WIDTH / 2 - image.get_width() / 2)
        y = int(world.y + world.PET_HEIGHT - image.get_height() + bob)
        shadow_width = max(35, int(70 * (1.0 - min(0.6, abs(world.y - (world.FLOOR_Y - world.PET_HEIGHT)) / 180))))
        pygame.draw.ellipse(
            surface,
            (31, 30, 38),
            (int(world.x + world.PET_WIDTH / 2 - shadow_width / 2), int(world.FLOOR_Y - 8), shadow_width, 12),
        )
        surface.blit(image, (x, y))

    def draw_overlay(
        self,
        surface: pygame.Surface,
        world: PetWorld,
        status: str,
        bubble: str,
        debug: bool,
        raw_vector: tuple[float, ...],
    ) -> None:
        panel = pygame.Surface((world.WIDTH, 54), pygame.SRCALPHA)
        panel.fill((9, 13, 23, 215))
        surface.blit(panel, (0, 0))
        surface.blit(self.title_font.render("SmolVLA Pet Sandbox", True, (247, 224, 191)), (18, 10))
        status_image = self.small_font.render(status, True, (176, 210, 221))
        surface.blit(status_image, (18, 35))
        hint = self.small_font.render("F1 debug   R reset   Esc quit", True, (152, 157, 174))
        surface.blit(hint, (world.WIDTH - hint.get_width() - 16, 20))

        if bubble:
            self._draw_bubble(surface, world, bubble)
        if debug:
            self._draw_debug(surface, world, raw_vector)

    def _draw_bubble(self, surface: pygame.Surface, world: PetWorld, text: str) -> None:
        lines = textwrap.wrap(text, width=30)[:3]
        rendered = [self.font.render(line, True, (42, 39, 51)) for line in lines]
        width = max((line.get_width() for line in rendered), default=100) + 28
        height = len(rendered) * 24 + 22
        x = int(max(10, min(world.WIDTH - width - 10, world.x + world.PET_WIDTH / 2 - width / 2)))
        y = int(max(68, world.y - height - 18))
        rect = pygame.Rect(x, y, width, height)
        pygame.draw.rect(surface, (255, 247, 225), rect, border_radius=13)
        pygame.draw.rect(surface, (121, 84, 70), rect, width=2, border_radius=13)
        pygame.draw.polygon(
            surface,
            (255, 247, 225),
            [(x + width // 2 - 9, y + height), (x + width // 2 + 9, y + height), (x + width // 2, y + height + 12)],
        )
        for index, line in enumerate(rendered):
            surface.blit(line, (x + 14, y + 11 + index * 24))

    def _draw_debug(self, surface: pygame.Surface, world: PetWorld, raw_vector: tuple[float, ...]) -> None:
        panel = pygame.Surface((340, 104), pygame.SRCALPHA)
        panel.fill((8, 12, 20, 210))
        surface.blit(panel, (world.WIDTH - 352, world.HEIGHT - 116))
        entries = [
            f"pose={world.pose.value} x={world.x:.1f} y={world.y:.1f}",
            f"velocity=({world.vx:.1f}, {world.vy:.1f}) ground={world.on_ground}",
            "raw=" + (", ".join(f"{v:.2f}" for v in raw_vector) if raw_vector else "waiting"),
            f"sequence={world.sequence_id} toy=({world.toy.x:.1f}, {world.toy.y:.1f})",
        ]
        for index, entry in enumerate(entries):
            image = self.small_font.render(entry, True, (184, 220, 201))
            surface.blit(image, (world.WIDTH - 340, world.HEIGHT - 106 + index * 23))

