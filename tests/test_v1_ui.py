from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWizard

from vla_pet.chat_dialog import PetChatDialog
from vla_pet.onboarding import OnboardingWizard
from vla_pet.settings import CompanionSettings


def test_onboarding_pet_only_choice_changes_runtime_setting() -> None:
    app = QApplication.instance() or QApplication([])
    assert app is not None
    settings = CompanionSettings()
    wizard = OnboardingWizard(
        settings,
        character_name="Momo",
        model_cache_ready=True,
        model_runtime_ready=True,
        microphone_ready=True,
        tts_ready=True,
    )
    wizard.pet_only.setChecked(True)
    wizard.memory.setChecked(True)
    wizard._store(QWizard.DialogCode.Accepted)
    assert settings.onboarding_completed
    assert not settings.ai_enabled
    assert settings.memory_enabled
    wizard.close()


def test_chat_incremental_render_and_cancel_do_not_duplicate_turns() -> None:
    app = QApplication.instance() or QApplication([])
    assert app is not None
    dialog = PetChatDialog()
    submitted: list[str] = []
    dialog.message_submitted.connect(submitted.append)
    dialog.input.setText("hello")
    dialog._submit()
    assert submitted == ["hello"] and not dialog.input.isEnabled()
    dialog.stream_pet_message("A short clean response")
    while dialog._stream_parts:
        dialog._stream_step()
    assert dialog.history == (("user", "hello"), ("pet", "A short clean response"))
    dialog.set_waiting(True)
    dialog._cancel()
    assert dialog.input.isEnabled()
    dialog.close()


def test_settings_round_trip_v1_provider_and_update_choices() -> None:
    original = CompanionSettings(
        ai_enabled=False,
        memory_enabled=True,
        update_channel="beta",
        auto_update_enabled=True,
        update_manifest_url="https://updates.example/release.json",
        update_public_key="YWJj",
        update_key_id="release-2026",
    )
    restored = CompanionSettings.from_dict(original.as_dict())
    assert restored == original
