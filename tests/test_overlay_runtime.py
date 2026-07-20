from __future__ import annotations

import os
import time
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication

import vla_pet.overlay as overlay_module
from vla_pet.overlay import DesktopPetOverlay, OverlayConfig
from vla_pet.worker import WorkerConfig


class BlockedAI:
    """Worker-shaped test double that never completes its queued decision."""

    def __init__(self, _config: WorkerConfig, _bus: object) -> None:
        self.pending_kinds = ("decide",)
        self.process_id = 4242

    def start(self) -> None:
        pass

    def submit(self, _kind: str, _payload: Any) -> None:
        pass

    def poll(self) -> list[object]:
        return []

    def timed_out(self) -> bool:
        return False

    def stop(self) -> None:
        pass


class MouseEventStub:
    def __init__(
        self,
        button: Qt.MouseButton,
        x: float,
        y: float,
        *,
        buttons: Qt.MouseButton = Qt.MouseButton.NoButton,
        modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
    ) -> None:
        self._button = button
        self._position = QPointF(x, y)
        self._buttons = buttons
        self._modifiers = modifiers
        self.accepted = False

    def button(self) -> Qt.MouseButton:
        return self._button

    def buttons(self) -> Qt.MouseButton:
        return self._buttons

    def modifiers(self) -> Qt.KeyboardModifier:
        return self._modifiers

    def globalPosition(self) -> QPointF:  # noqa: N802 - mirrors Qt API
        return self._position

    def accept(self) -> None:
        self.accepted = True


def build_overlay(monkeypatch) -> DesktopPetOverlay:
    monkeypatch.setattr(overlay_module, "AIOrchestrator", BlockedAI)
    app = QApplication.instance() or QApplication([])
    assert app is not None
    return DesktopPetOverlay(
        OverlayConfig(
            worker=WorkerConfig(mock_policy=True),
            safe_mode=True,
            logging=False,
            interaction_padding=72,
        )
    )


def test_overlay_heartbeat_and_local_walk_continue_while_ai_is_blocked(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    started = time.monotonic()
    overlay = build_overlay(monkeypatch)
    overlay._tick()
    assert time.monotonic() - started < 1.0
    heartbeats: list[float] = []
    overlay.timer.timeout.connect(lambda: heartbeats.append(time.monotonic()))
    starting_x = overlay.world.x
    deadline = time.monotonic() + 0.18
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.003)
    assert len(heartbeats) >= 5
    assert overlay.world.x != starting_x
    overlay.shutdown()
    overlay.close()


def test_overlay_left_drag_drop_and_ctrl_click_remain_interactive(monkeypatch) -> None:
    overlay = build_overlay(monkeypatch)
    opened: list[bool] = []
    monkeypatch.setattr(overlay, "_open_chat", lambda: opened.append(True))

    ctrl_click = MouseEventStub(
        Qt.MouseButton.LeftButton,
        100,
        100,
        modifiers=Qt.KeyboardModifier.ControlModifier,
    )
    overlay._interaction_mouse_press(ctrl_click)  # type: ignore[arg-type]
    assert ctrl_click.accepted and opened == [True]

    press = MouseEventStub(Qt.MouseButton.LeftButton, 100, 100)
    overlay._interaction_mouse_press(press)  # type: ignore[arg-type]
    assert press.accepted and overlay._dragging and overlay.world.being_held
    move = MouseEventStub(
        Qt.MouseButton.NoButton,
        160,
        55,
        buttons=Qt.MouseButton.LeftButton,
    )
    overlay._interaction_mouse_move(move)  # type: ignore[arg-type]
    assert move.accepted and overlay._drag_moved
    release = MouseEventStub(Qt.MouseButton.LeftButton, 160, 55)
    overlay._interaction_mouse_release(release)  # type: ignore[arg-type]
    assert release.accepted and not overlay._dragging and not overlay.world.being_held
    assert overlay.world.user_falling or overlay.world.on_ground

    sprite, _x, _y = overlay._sprite_geometry()
    bounds = overlay._interaction_region().boundingRect()
    assert bounds.width() >= sprite.width() + 2 * overlay.config.interaction_padding
    overlay.shutdown()
    overlay.close()


def test_overlay_habitat_is_masked_draggable_and_uses_only_synthetic_pixels(monkeypatch) -> None:
    overlay = build_overlay(monkeypatch)
    monkeypatch.setattr(
        overlay.screen_capture,
        "request",
        lambda: (_ for _ in ()).throw(AssertionError("desktop capture must not run")),
    )
    observation = overlay._build_habitat_observation()
    assert observation.image.shape == (3, 256, 256)
    habitat = overlay._habitat_rect()
    assert habitat.width() == 420 and habitat.height() == 190
    assert overlay._interaction_region().contains(habitat.center())

    ball = overlay._habitat_object_rect("ball")
    geometry = overlay.geometry()
    press = MouseEventStub(
        Qt.MouseButton.LeftButton,
        geometry.x() + ball.center().x(),
        geometry.y() + ball.center().y(),
    )
    overlay._interaction_mouse_press(press)  # type: ignore[arg-type]
    assert press.accepted and overlay._drag_object_id == "ball"
    move = MouseEventStub(
        Qt.MouseButton.NoButton,
        geometry.x() + ball.center().x() - 60,
        geometry.y() + ball.center().y() - 45,
        buttons=Qt.MouseButton.LeftButton,
    )
    overlay._interaction_mouse_move(move)  # type: ignore[arg-type]
    release = MouseEventStub(
        Qt.MouseButton.LeftButton,
        geometry.x() + ball.center().x() - 60,
        geometry.y() + ball.center().y() - 45,
    )
    overlay._interaction_mouse_release(release)  # type: ignore[arg-type]
    assert release.accepted and not overlay._drag_object_id
    assert overlay.habitat_controller.object("ball").status.value == "airborne"
    overlay._set_habitat_collapsed(True)
    assert overlay._habitat_rect().size().width() == 44
    overlay.shutdown()
    overlay.close()


def test_overlay_switches_stage_sprite_and_announces_evolution(monkeypatch) -> None:
    overlay = build_overlay(monkeypatch)
    saved: list[bool] = []
    monkeypatch.setattr(overlay.runtime, "save", lambda: saved.append(True))
    monkeypatch.setattr(overlay, "_play_soft_sound", lambda: None)
    overlay.runtime.state.growth.stage = "baby"
    overlay._visible_growth_stage = "baby"
    overlay.animation.set_stage("baby", 1.0)
    baby_height = overlay._scaled_sprite("idle").height()

    overlay.runtime.state.growth.stage = "child"
    overlay.runtime.state.progression.xp = 300
    overlay._update_growth_animation(10.0)

    assert overlay.animation.stage == "child"
    assert overlay._visible_growth_stage == "child"
    assert overlay._evolution_until == 12.0
    assert "grew into Child" in overlay.bubble
    assert overlay._scaled_sprite("idle").height() > baby_height
    assert saved == [True]
    overlay.shutdown()
    overlay.close()
