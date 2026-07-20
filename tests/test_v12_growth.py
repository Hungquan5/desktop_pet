from __future__ import annotations

import os
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from vla_pet.animation import AnimationController
from vla_pet.character import FIXED_ANIMATION_ROLES, CharacterPack, default_character_directory
from vla_pet.chat_dialog import PetChatDialog
from vla_pet.companion_panel import CompanionPanel
from vla_pet.contracts import ChatRequest, WorkerRequest
from vla_pet.control_center import CompanionControlCenter
from vla_pet.growth import GrowthEngine, GrowthStage, companion_status_text, stage_progress
from vla_pet.habitat import HabitatState
from vla_pet.persistence import StateRepository
from vla_pet.progression import ProgressionEngine
from vla_pet.settings import CompanionSettings
from vla_pet.state import PetRuntimeState
from vla_pet.worker import MockRequestHandler, WorkerConfig


def test_schema_two_state_migrates_to_positive_teen_growth() -> None:
    state = PetRuntimeState.from_snapshot(
        {
            "schema_version": 2,
            "progression": {"xp": 1000, "level": 1, "inventory": {"ball": 1}},
            "needs": {"energy": 0.6},
        }
    )
    assert state.schema_version == 3
    assert state.progression.level == 11
    assert state.growth.stage == GrowthStage.TEEN.value
    assert state.growth.evolution_history == ["baby", "child", "teen"]
    assert (state.stats.health, state.stats.stamina, state.stats.intelligence) == (18, 16, 14)


def test_growth_thresholds_evolve_once_and_never_regress() -> None:
    state = PetRuntimeState()
    progression = ProgressionEngine()
    state.progression.xp = 299
    result = progression.award(state, 1, reason="daily")
    assert result.evolved and result.stage_after is GrowthStage.CHILD
    assert state.growth.stage == "child"
    assert "evolved_child" in result.unlocked
    child_stats = (state.stats.health, state.stats.stamina, state.stats.intelligence)

    state.progression.xp = 999
    result = progression.award(state, 1, reason="focus")
    assert result.stage_before is GrowthStage.CHILD and result.stage_after is GrowthStage.TEEN
    assert all(after >= before + 5 for before, after in zip(child_stats, (
        state.stats.health,
        state.stats.stamina,
        state.stats.intelligence,
    ), strict=True))
    state.progression.xp = 0
    assert GrowthEngine().reconcile(state).after is GrowthStage.TEEN


def test_specialized_stats_gain_from_completed_activity() -> None:
    state = PetRuntimeState()
    growth = GrowthEngine()
    threshold = growth.stat_threshold(state.stats.stamina)
    state.stats.stamina_xp = threshold - 1
    gains = growth.award_activity(state, "chase_ball", magnitude=2)
    assert state.stats.stamina == 9
    assert dict(gains)["stamina"] == 1
    assert state.stats.intelligence_xp == 1

    int_before = state.stats.intelligence_xp
    growth.award_activity(state, "focus", magnitude=8)
    assert state.stats.intelligence_xp > int_before or state.stats.intelligence > 6


def test_daily_streak_resets_after_gap_and_ball_is_durable() -> None:
    state = PetRuntimeState()
    progression = ProgressionEngine()
    state.progression.last_daily_date = "2026-07-18"
    state.progression.daily_streak = 3
    assert progression.daily_check_in(state, today=date(2026, 7, 19)).xp_awarded == 10
    assert state.progression.daily_streak == 4
    assert progression.daily_check_in(state, today=date(2026, 7, 19)).xp_awarded == 0
    progression.daily_check_in(state, today=date(2026, 7, 21))
    assert state.progression.daily_streak == 1

    assert progression.use_item(state, "ball")
    assert state.progression.inventory["ball"] == 1
    snacks = state.progression.inventory["snack"]
    assert progression.use_item(state, "snack")
    assert state.progression.inventory.get("snack", 0) == snacks - 1


def test_growth_state_persists_with_existing_database_schema(tmp_path: Path) -> None:
    database = tmp_path / "pet.db"
    state = PetRuntimeState()
    state.progression.xp = 300
    ProgressionEngine().award(state, 0, reason="progress")
    state.stats.intelligence = 17
    with StateRepository(database) as repository:
        repository.save_state(state)
    with StateRepository(database) as repository:
        restored = repository.load_state()
    assert restored.growth.stage == "child"
    assert restored.stats.intelligence == 17


def test_schema_four_pack_has_fixed_roles_for_every_growth_stage() -> None:
    pack = CharacterPack.load(default_character_directory())
    assert pack.schema_version == 4 and pack.pack_version == "3.1.0"
    assert set(pack.growth_stages) == {"baby", "child", "teen"}
    for stage in pack.growth_stages:
        assert all(pack.animation_for(role, stage).frames for role in FIXED_ANIMATION_ROLES)
    assert "child" in str(pack.animation_for("idle", "child").frames[0])
    assert "teen" in str(pack.animation_for("idle", "teen").frames[0])
    controller = AnimationController(pack)
    assert controller.set_stage("child", 1.0)
    assert "child" in controller.frame_role(1.1, "walk")
    assert controller.set_stage("teen", 2.0)
    assert "teen" in controller.frame_role(2.1, "talk")
    assert pack.scale_for_stage("teen") >= pack.scale_for_stage("child") + 0.15


def test_builtin_growth_frames_are_isolated_and_have_safe_edges() -> None:
    pack = CharacterPack.load(default_character_directory())
    paths = {
        path
        for spec in pack.animation_specs()
        for path in spec.frames
    }
    assert len(paths) == 52
    for path in paths:
        image = QImage(str(path)).convertToFormat(QImage.Format.Format_RGBA8888)
        assert image.width() == 128 and image.height() == 128 and image.hasAlphaChannel()
        edge_alpha = [
            *(image.pixelColor(x, 0).alpha() for x in range(128)),
            *(image.pixelColor(x, 127).alpha() for x in range(128)),
            *(image.pixelColor(0, y).alpha() for y in range(128)),
            *(image.pixelColor(127, y).alpha() for y in range(128)),
        ]
        assert max(edge_alpha) <= 8, f"sprite touches crop edge: {path}"


def test_status_page_shows_form_stats_and_full_affection() -> None:
    app = QApplication.instance() or QApplication([])
    assert app is not None
    settings = CompanionSettings()
    state = PetRuntimeState()
    state.progression.affection_points = 100
    state.progression.xp = 300
    ProgressionEngine().award(state, 0)
    chat = PetChatDialog()
    advanced = CompanionControlCenter(settings, None, None, None, state, HabitatState())
    panel = CompanionPanel(settings, state, chat, advanced)
    assert panel.pages.count() == 5
    panel.set_page("status")
    assert panel.pages.currentIndex() == 2
    assert panel.affection.value() == 100
    assert "Child" in panel.stage_label.text()
    assert panel.stat_bars["health"].value() == state.stats.health
    panel.close()


def test_live_status_is_available_to_the_language_layer() -> None:
    state = PetRuntimeState()
    context = companion_status_text(state)
    request = ChatRequest("What are your stats?", companion_context=context)
    response = MockRequestHandler(WorkerConfig(mock_policy=True)).handle(
        WorkerRequest(1, "chat", request)
    )
    assert response.ok
    assert "health 10" in response.payload.reply
    assert stage_progress(0).next_stage is GrowthStage.CHILD
