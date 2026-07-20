from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from vla_pet.animation import AnimationController
from vla_pet.character import CharacterPack, default_character_directory
from vla_pet.chat_dialog import PetChatDialog
from vla_pet.companion_panel import CompanionPanel
from vla_pet.contracts import HabitatIntent, WorkerRequest
from vla_pet.control_center import CompanionControlCenter
from vla_pet.habitat import (
    HabitatController,
    HabitatObjectStatus,
    HabitatObservation,
    HabitatState,
)
from vla_pet.persistence import StateRepository
from vla_pet.policy import infer_habitat_intent
from vla_pet.settings import CompanionSettings
from vla_pet.state import PetRuntimeState
from vla_pet.worker import MockRequestHandler, WorkerConfig


def test_settings_schema_one_migrates_to_cozy_schema_two() -> None:
    settings = CompanionSettings.from_dict(
        {
            "schema_version": 1,
            "ai_enabled": False,
            "persona_name": "Momo local",
        }
    )
    assert settings.schema_version == 2
    assert not settings.ai_enabled and settings.persona_name == "Momo local"
    assert settings.habitat_enabled and not settings.habitat_collapsed
    assert not settings.sound_enabled and settings.last_panel_page == "home"


def test_habitat_ball_physics_collapse_and_restore_are_bounded() -> None:
    controller = HabitatController()
    assert controller.start_drag("ball")
    assert controller.drag_to("ball", 0.95, 0.18)
    assert controller.release_drag("ball", 520.0, -280.0)
    ball = controller.object("ball")
    assert ball is not None and ball.status is HabitatObjectStatus.AIRBORNE
    assert any(controller.update(1 / 60) for _ in range(240))
    assert 0.0 <= ball.x <= 1.0 and 0.0 <= ball.y <= 1.0
    controller.set_collapsed(True)
    assert ball.vx == ball.vy == 0.0 and ball.status is HabitatObjectStatus.PLACED
    restored = HabitatState.from_snapshot(controller.state.snapshot())
    restored_ball = next(item for item in restored.objects if item.object_id == "ball")
    assert restored.collapsed and restored_ball.vx == restored_ball.vy == 0.0


def test_snack_consumption_and_reward_completion_are_idempotent() -> None:
    controller = HabitatController()
    assert controller.spawn_snack(2)
    assert not controller.spawn_snack(2)
    assert controller.begin_interaction(HabitatIntent.EAT_SNACK, "snack", 10.0)
    first = controller.complete_interaction(token="eat-1", object_id="snack", now=12.0)
    duplicate = controller.complete_interaction(token="eat-1", object_id="snack", now=13.0)
    assert first.accepted and first.reward_allowed
    assert not duplicate.accepted and not duplicate.reward_allowed
    assert controller.consume_snack() and not controller.consume_snack()
    assert controller.spawn_snack(1)
    assert controller.begin_interaction(HabitatIntent.EAT_SNACK, "snack", 20.0)
    cooldown = controller.complete_interaction(token="eat-2", object_id="snack", now=25.0)
    assert cooldown.accepted and not cooldown.reward_allowed


def test_schema_three_atomically_restores_habitat_without_velocity(tmp_path: Path) -> None:
    database = tmp_path / "pet.db"
    with StateRepository(database) as repository:
        state = PetRuntimeState()
        state.progression.xp = 44
        habitat = HabitatState(anchor_x=0.25)
        ball = next(item for item in habitat.objects if item.object_id == "ball")
        ball.vx, ball.vy = 300.0, -90.0
        ball.status = HabitatObjectStatus.AIRBORNE
        repository.save_companion_state(state, habitat)
    with StateRepository(database) as repository:
        assert repository.load_state().progression.xp == 44
        restored = repository.load_habitat()
        restored_ball = next(item for item in restored.objects if item.object_id == "ball")
        assert restored.anchor_x == 0.25
        assert restored_ball.vx == restored_ball.vy == 0.0
        assert restored_ball.status is HabitatObjectStatus.PLACED

    connection = sqlite3.connect(database)
    connection.execute("DROP TABLE habitat_state")
    connection.execute("PRAGMA user_version = 2")
    connection.commit()
    connection.close()
    with StateRepository(database) as repository:
        assert repository.load_habitat().enabled
    backup = database.with_name("pet.db.pre-v3-from-v2.bak")
    assert backup.is_file() and backup.stat().st_mode & 0o777 == 0o600


def test_character_schema_three_roles_and_old_pack_fallback() -> None:
    pack = CharacterPack.load(default_character_directory())
    assert pack.schema_version == 3 and pack.pack_version == "2.0.0"
    assert len(pack.animation_for("walk").frames) == 2
    assert pack.animation_for("held").name == "held"
    controller = AnimationController(pack)
    assert controller.select_role("sleep", 1.0, force=True)
    assert Path(controller.frame_role(1.2)).is_file()
    old = CharacterPack.load(Path(__file__).resolve().parents[1] / "characters" / "orbit")
    assert old.schema_version == 2
    assert old.animation_for("sleep") == old.animations[next(k for k in old.animations if k.value == "idle")]


def test_smollm_direct_habitat_intents_and_mock_worker_share_contract() -> None:
    assert infer_habitat_intent("can you please take a nap on the cushion") is HabitatIntent.REST
    assert infer_habitat_intent("could you play with the ball") is HabitatIntent.CHASE_BALL
    assert infer_habitat_intent("what color is the ball?") is None
    controller = HabitatController()
    environment = controller.environment_snapshot(
        pet_x=0.5,
        pet_y=1.0,
        energy=0.8,
        boredom=0.2,
        curiosity=0.5,
        snack_count=2,
    )
    request = HabitatObservation(7, np.zeros((3, 256, 256), dtype=np.float32), environment)
    response = MockRequestHandler(WorkerConfig(mock_policy=True)).handle(
        WorkerRequest(1, "habitat", request)
    )
    assert response.ok and response.payload in environment.candidates


def test_unified_panel_has_four_friendly_pages_and_embedded_chat() -> None:
    app = QApplication.instance() or QApplication([])
    assert app is not None
    settings = CompanionSettings()
    state = PetRuntimeState()
    chat = PetChatDialog()
    advanced = CompanionControlCenter(settings, None, None, None, state, HabitatState())
    panel = CompanionPanel(settings, state, chat, advanced)
    assert panel.pages.count() == 4
    panel.set_page("chat")
    assert panel.pages.currentIndex() == 1 and settings.last_panel_page == "chat"
    panel.set_page("play")
    assert "Snack" in panel.inventory_label.text()
    panel.sound_enabled.setChecked(True)
    panel.sound_volume.setValue(20)
    panel._save_simple_settings()
    assert settings.sound_enabled and settings.sound_volume == 0.2
    panel.close()


def test_habitat_domain_update_stays_well_below_frame_budget() -> None:
    controller = HabitatController()
    assert controller.start_drag("ball")
    assert controller.release_drag("ball", 600.0, -400.0)
    started = time.perf_counter()
    for _ in range(20_000):
        controller.update(1 / 60)
    assert time.perf_counter() - started < 0.35
