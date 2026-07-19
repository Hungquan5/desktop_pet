from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import pygame

from vla_pet.contracts import ActionKind, LanguageNarration, PetAction
from vla_pet.observation import build_observation
from vla_pet.rendering import Renderer
from vla_pet.session_log import SessionLogger
from vla_pet.worker import AIWorkerClient, WorkerConfig
from vla_pet.world import PetWorld


@dataclass(slots=True)
class AppConfig:
    worker: WorkerConfig
    fps: int = 60
    debug: bool = False
    headless: bool = False
    max_seconds: float | None = None
    logging: bool = True
    asset_directory: Path | None = None


class PetSandboxApp:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        pygame.init()
        flags = 0 if config.headless else pygame.RESIZABLE
        self.window = pygame.display.set_mode((PetWorld.WIDTH, PetWorld.HEIGHT), flags)
        pygame.display.set_caption("SmolVLM + SmolLM Pet Sandbox")
        self.canvas = pygame.Surface((PetWorld.WIDTH, PetWorld.HEIGHT)).convert()
        self.world = PetWorld()
        self.renderer = Renderer(config.asset_directory)
        self.logger = SessionLogger(enabled=config.logging)
        self.worker = AIWorkerClient(config.worker)
        self.clock = pygame.time.Clock()
        self.running = True
        self.started_at = time.monotonic()
        self.debug = config.debug
        self.status = "Starting local AI worker…"
        self.bubble = ""
        self.bubble_until = 0.0
        self.raw_vector: tuple[float, ...] = ()
        self.last_decision_latency = 0.0
        self.next_decision_at = 0.0

    def run(self) -> int:
        self.worker.start()
        self.logger.write(
            "session_start",
            model_id=self.config.worker.model_id,
            device=self.config.worker.device,
            mock_policy=self.config.worker.mock_policy,
        )
        try:
            while self.running:
                dt = self.clock.tick(self.config.fps) / 1000.0
                now = time.monotonic()
                self._handle_input()
                action_event = self.world.update(dt)
                if action_event:
                    self.logger.write("action_completed", **action_event.as_dict())
                    if (
                        action_event.executed is not ActionKind.WALK
                        and "narrate" not in self.worker.pending_kinds
                    ):
                        self.worker.submit("narrate", LanguageNarration(action_event))
                    self.next_decision_at = now + 0.15

                self.renderer.draw_world(self.canvas, self.world, now - self.started_at)
                self._handle_worker_responses(now)
                self._request_decision_if_ready(now)
                self._draw_frame(now)

                if self.worker.timed_out():
                    self.status = "AI worker timed out; continuing safely in idle"
                    self.logger.write("worker_timeout", timeout_s=self.config.worker.timeout_s)
                    self.worker.stop()
                    self.worker = AIWorkerClient(self.config.worker)
                    self.worker.start()

                if self.config.max_seconds is not None and now - self.started_at >= self.config.max_seconds:
                    self.running = False
        finally:
            self.worker.stop()
            self.logger.write("session_end")
            pygame.quit()
        return 0

    def _handle_input(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_r:
                    self.world.reset()
                    self.bubble = ""
                    self.logger.write("world_reset", sequence_id=self.world.sequence_id)
                elif event.key == pygame.K_F1:
                    self.debug = not self.debug

    def _handle_worker_responses(self, now: float) -> None:
        for response in self.worker.poll():
            if response.kind == "decide":
                expected_sequence = response.metadata.get("sequence_id")
                if expected_sequence != self.world.sequence_id or self.world.is_busy:
                    self.logger.write(
                        "stale_decision",
                        request_id=response.request_id,
                        observed_sequence=expected_sequence,
                        current_sequence=self.world.sequence_id,
                    )
                    continue
                action: PetAction = response.payload
                self.raw_vector = action.raw_vector
                self.last_decision_latency = response.latency_s
                self.world.apply_action(action)
                self.status = (
                    f"{response.provider}: {action.kind.value} • inference {response.latency_s:.2f}s"
                    if response.ok
                    else f"Fallback idle • {response.error}"
                )
                self.logger.write(
                    "decision",
                    ok=response.ok,
                    provider=response.provider,
                    latency_s=round(response.latency_s, 4),
                    error=response.error,
                    action=action.as_dict(),
                )
            elif response.kind == "narrate":
                self.bubble = str(response.payload)
                self.bubble_until = now + 4.5
                if not response.ok:
                    self.status = f"Narration fallback • {response.error}"
                self.logger.write(
                    "narration",
                    ok=response.ok,
                    provider=response.provider,
                    latency_s=round(response.latency_s, 4),
                    error=response.error,
                    text=self.bubble,
                )

    def _request_decision_if_ready(self, now: float) -> None:
        if self.world.is_busy or now < self.next_decision_at:
            return
        if "decide" in self.worker.pending_kinds:
            return
        observation = build_observation(self.canvas, self.world)
        self.worker.submit("decide", observation)
        provider = "mock policy" if self.config.worker.mock_policy else self.config.worker.model_id
        self.status = f"{provider}: thinking in background…"
        self.logger.write("observation", sequence_id=observation.sequence_id, state=observation.state)

    def _draw_frame(self, now: float) -> None:
        if now >= self.bubble_until:
            self.bubble = ""
        frame = self.canvas.copy()
        self.renderer.draw_overlay(frame, self.world, self.status, self.bubble, self.debug, self.raw_vector)
        window_size = self.window.get_size()
        if window_size == frame.get_size():
            self.window.blit(frame, (0, 0))
        else:
            scaled = pygame.transform.smoothscale(frame, window_size)
            self.window.blit(scaled, (0, 0))
        pygame.display.flip()
