from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from vla_pet.settings import CompanionSettings
from vla_pet.theme import apply_companion_theme


class OnboardingWizard(QWizard):
    def __init__(
        self,
        settings: CompanionSettings,
        *,
        character_name: str,
        model_cache_ready: bool,
        model_runtime_ready: bool,
        microphone_ready: bool,
        tts_ready: bool,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.setWindowTitle("Welcome to your local desktop companion")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.addPage(self._welcome())
        self.addPage(self._privacy())
        self.addPage(self._ai(model_cache_ready, model_runtime_ready))
        self.addPage(self._voice(microphone_ready, tts_ready))
        self.addPage(self._finish(character_name))
        self.finished.connect(self._store)
        apply_companion_theme(self)

    def _welcome(self) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("A pet first, an assistant when you ask")
        layout = QVBoxLayout(page)
        layout.addWidget(
            QLabel(
                "The pet stays alive without AI. Screen, microphone, notifications, files, tools, "
                "memory, plugins, and updates remain off until you choose them."
            )
        )
        return page

    def _privacy(self) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("Choose local memory and awareness")
        layout = QVBoxLayout(page)
        self.memory = QCheckBox("Remember explicit preferences, tasks, and shared events")
        self.notifications = QCheckBox("Read notifications during this session")
        self.proactive = QCheckBox("Allow rate-limited proactive suggestions with visible reasons")
        layout.addWidget(self.memory)
        layout.addWidget(self.notifications)
        layout.addWidget(self.proactive)
        layout.addWidget(QLabel("You can inspect, export, delete, or disable these later."))
        return page

    def _ai(self, cache_ready: bool, runtime_ready: bool) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("Choose cognition")
        layout = QVBoxLayout(page)
        self.local_ai = QRadioButton("Use local SmolLM + SmolVLM")
        self.local_ai.setEnabled(runtime_ready)
        self.local_ai.setChecked(runtime_ready)
        self.pet_only = QRadioButton("Pet-only mode without models")
        self.pet_only.setChecked(not runtime_ready)
        layout.addWidget(self.local_ai)
        layout.addWidget(self.pet_only)
        layout.addWidget(
            QLabel(
                "Cached models are ready."
                if cache_ready and runtime_ready
                else (
                    "The model runtime is ready; weights download after consent."
                    if runtime_ready
                    else "Install with --models to enable local cognition."
                )
            )
        )
        return page

    def _voice(self, microphone_ready: bool, tts_ready: bool) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("Optional voice")
        layout = QVBoxLayout(page)
        self.voice = QCheckBox("Enable push-to-talk microphone")
        self.voice.setEnabled(microphone_ready)
        self.tts = QCheckBox("Read replies aloud")
        self.tts.setEnabled(tts_ready)
        layout.addWidget(self.voice)
        layout.addWidget(self.tts)
        layout.addWidget(
            QLabel(
                f"Capture: {'available' if microphone_ready else 'unavailable'} • "
                f"speech playback: {'available' if tts_ready else 'unavailable'}"
            )
        )
        return page

    def _finish(self, character_name: str) -> QWizardPage:
        page = QWizardPage()
        page.setTitle(f"Meet {character_name}")
        layout = QVBoxLayout(page)
        layout.addWidget(
            QLabel(
                "Left-drag to move the pet, Ctrl-click to chat, right-click for an authorized "
                "screen question, and open the paw nook for snacks, ball play, naps, and boxes. "
                "The nook can be collapsed or disabled at any time."
            )
        )
        return page

    def _store(self, result: int) -> None:
        if result != QWizard.DialogCode.Accepted:
            return
        self.settings.onboarding_completed = True
        self.settings.ai_enabled = self.local_ai.isChecked()
        self.settings.memory_enabled = self.memory.isChecked()
        self.settings.notifications_enabled = self.notifications.isChecked()
        self.settings.proactive_enabled = self.proactive.isChecked()
        self.settings.voice_enabled = self.voice.isChecked()
        self.settings.tts_enabled = self.tts.isChecked()
