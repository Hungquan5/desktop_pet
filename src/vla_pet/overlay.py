from __future__ import annotations

import os
import signal
import sys
import tempfile
import threading
import time
import urllib.parse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from importlib.util import find_spec
from pathlib import Path

import numpy as np
from PySide6.QtCore import QLockFile, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QRegion,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
    QWidget,
)

from vla_pet import __version__
from vla_pet.ai_orchestrator import AIOrchestrator
from vla_pet.animation import AnimationController
from vla_pet.async_tools import AsyncToolExecutor
from vla_pet.awareness import (
    AwarenessService,
    AwarenessSettings,
    DesktopContext,
    LinuxContextProbe,
    ProactivePolicy,
)
from vla_pet.builtin_tools import CoreToolServices, ToolIntentParser, register_core_tools
from vla_pet.character import CharacterPack, load_character_or_default
from vla_pet.chat_dialog import PetChatDialog
from vla_pet.contracts import (
    ActionIntent,
    ActionKind,
    AudioTranscription,
    ChatRequest,
    ChatResult,
    LanguageNarration,
    NotificationRequest,
    PetAction,
    SandboxObservation,
    VisualQuestion,
)
from vla_pet.control_center import CompanionControlCenter
from vla_pet.events import PlatformEvent, UserInteractionEvent
from vla_pet.life import LifeContext, LifeDecision, LifeIntent
from vla_pet.onboarding import OnboardingWizard
from vla_pet.overlay_actions import OverlayActionScheduler, sprite_needs_flip
from vla_pet.paths import AppPaths
from vla_pet.permissions import Capability, PermissionLifetime, PermissionPolicy
from vla_pet.platform_adapters import (
    NotificationMonitor,
    ScreenCaptureAdapter,
    open_allowed_application,
)
from vla_pet.plugin_dispatcher import AsyncPluginDispatcher
from vla_pet.plugins import PluginHost, PluginManifest, default_plugin_directory
from vla_pet.runtime import RuntimeController
from vla_pet.session_log import SessionLogger
from vla_pet.settings import CompanionSettings
from vla_pet.tool_runtime import ToolRegistry
from vla_pet.update_service import AsyncUpdateChecker
from vla_pet.updater import UpdateArtifact
from vla_pet.voice import (
    ArecordCapture,
    AudioSession,
    AudioState,
    CommandSTTProvider,
    UnavailableSTTProvider,
)
from vla_pet.voice_qt import QtSpeechProvider
from vla_pet.worker import WorkerConfig
from vla_pet.world import PetWorld

OVERLAY_TASK_PROMPT = "Walk around the screen safely without interacting with desktop applications."


def decision_request_ready(
    *,
    world_busy: bool,
    on_ground: bool,
    dragging: bool,
    now: float,
    next_decision_at: float,
    pending_kinds: tuple[str, ...],
) -> bool:
    """Keep locomotion decisions flowing while optional VLM replies are queued."""
    return not (
        world_busy
        or not on_ground
        or dragging
        or now < next_decision_at
        or "decide" in pending_kinds
    )


@dataclass(slots=True)
class OverlayConfig:
    worker: WorkerConfig
    debug: bool = False
    screen_index: int = 0
    pet_size: int = 128
    max_seconds: float | None = None
    logging: bool = True
    asset_directory: Path | None = None
    watch_notifications: bool = False
    interaction_padding: int = 64
    safe_mode: bool = False
    persist_conversation: bool = False
    semantic_interval_s: float = 15.0
    skip_onboarding: bool = False
    stt_command: tuple[str, ...] = ()


class DesktopPetOverlay(QWidget):
    audio_state_signal = Signal(str)
    audio_partial_signal = Signal(str)
    audio_result_signal = Signal(object, str)

    def __init__(self, config: OverlayConfig) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        super().__init__(None, flags)
        self.config = config
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        screens = QGuiApplication.screens()
        screen_index = max(0, min(config.screen_index, len(screens) - 1))
        self.screen = screens[screen_index]
        geometry = self.screen.availableGeometry()
        self.setGeometry(geometry)
        self.setWindowTitle("SmolVLM Desktop Pet")

        self.world = PetWorld(
            width=max(320, geometry.width()),
            height=max(240, geometry.height()),
            floor_y=max(180.0, geometry.height() - 8.0),
            bounce_edges=True,
            environment_label="screen",
            require_throw_target=False,
        )
        self.paths = AppPaths.discover()
        self.runtime = RuntimeController.from_database(
            self.paths.database,
            enabled=not config.safe_mode,
        )
        self.settings = CompanionSettings.load(self.runtime.repository)
        self._first_run_onboarding = bool(
            not config.skip_onboarding
            and not self.settings.onboarding_completed
            and QGuiApplication.platformName() != "offscreen"
        )
        if config.persist_conversation:
            self.settings.persist_conversation = True
        if config.watch_notifications:
            self.settings.notifications_enabled = True
        if config.safe_mode:
            self.settings = CompanionSettings(onboarding_completed=True)
        self.runtime.memory_enabled = self.settings.memory_enabled
        self.runtime.state.privacy_mode = self.settings.privacy_mode
        self.world.move_horizontal(
            self.runtime.state.x * max(1.0, self.world.WIDTH - self.world.PET_WIDTH)
        )
        allowed_capabilities: set[Capability] = {
            Capability.TIMER_MANAGE,
            Capability.TODO_MANAGE,
            Capability.REMINDER_MANAGE,
            Capability.NOTE_MANAGE,
        }
        if self.settings.notifications_enabled:
            allowed_capabilities.add(Capability.NOTIFICATION_MONITOR_SESSION)
        if self.settings.persist_conversation:
            allowed_capabilities.add(Capability.PERSIST_CONVERSATION)
        if self.settings.voice_enabled:
            allowed_capabilities.add(Capability.MICROPHONE_CAPTURE)
        if self.settings.active_window_enabled or self.settings.coding_status_enabled:
            allowed_capabilities.add(Capability.ACTIVE_WINDOW_READ)
        if self.settings.idle_detection_enabled:
            allowed_capabilities.add(Capability.USER_IDLE_READ)
        if self.settings.system_status_enabled:
            allowed_capabilities.add(Capability.SYSTEM_STATUS_READ)
        self.permissions = PermissionPolicy(allowed_capabilities, safe_mode=config.safe_mode)
        self._configure_update_permission()
        self.scheduler = OverlayActionScheduler()
        self.edge_bounced_pending = False
        character_result = load_character_or_default(config.asset_directory)
        self.character = character_result.pack
        if self.settings.persona_name or self.settings.persona_prompt:
            config.worker = replace(
                config.worker,
                persona_name=self.settings.persona_name or self.character.persona.name,
                persona_prompt=self.settings.persona_prompt or self.character.persona.system_prompt,
            )
        self._base_worker_config = config.worker
        self.animation = AnimationController(self.character, started_at=time.monotonic())
        self.sprites = self._load_sprites(self.character)
        self._sprite_cache: dict[tuple[str, int, bool], QPixmap] = {}
        self._bubble_cache: dict[str, QPixmap] = {}
        active_worker = (
            replace(config.worker, mock_policy=True)
            if self._first_run_onboarding or not self.settings.ai_enabled
            else config.worker
        )
        self.ai = AIOrchestrator(active_worker, self.runtime.bus)
        self.logger = SessionLogger(directory=self.paths.log_directory, enabled=config.logging)
        self.started_at = time.monotonic()
        self.last_tick = self.started_at
        self.next_decision_at = 0.0
        self.next_cognition_at = self.started_at
        self._last_persist_at = self.started_at
        self._life_decision: LifeDecision | None = None
        self._life_routine_step = 0
        self.bubble = "Drag me anywhere. Ctrl+click to chat. Right-click to inspect the screen."
        self.bubble_until = self.started_at + 9.0
        self.status = (
            "Pet-only mode — local AI is not running"
            if active_worker.mock_policy
            else "Loading local cognition…"
        )
        self.raw_vector: tuple[float, ...] = ()
        self.latest_notification = ""
        self._last_notification_at = 0.0
        self.screen_capture = ScreenCaptureAdapter(self.screen, self)
        self.screen_capture.finished.connect(self._on_screen_capture)
        self._pending_screen_question: tuple[str, str] | None = None
        self._pending_user_action: ActionIntent | None = None
        self._dragging = False
        self._drag_moved = False
        self._press_global_x = 0.0
        self._press_global_y = 0.0
        self._press_world_x = 0.0
        self._press_world_y = 0.0
        self._last_visual_rect = QRect()
        self._last_render_signature: tuple[object, ...] | None = None
        self._pending_mask = QRegion()
        self._shrink_mask_after_paint = False
        self._last_mask_context: tuple[bool, bool] | None = None
        self._mask_supported = QGuiApplication.platformName() != "offscreen"
        self.chat_dialog = PetChatDialog()
        self.chat_dialog.message_submitted.connect(self._submit_chat)
        self.chat_dialog.cancel_requested.connect(self._cancel_chat)
        self.chat_dialog.settings_requested.connect(self._open_control_center)
        self.chat_dialog.voice_requested.connect(self._toggle_voice)
        if self.runtime.persistence_enabled and self.permissions.permits(
            Capability.PERSIST_CONVERSATION
        ):
            self.chat_dialog.restore_history(self.runtime.conversation_history())

        self.tool_registry: ToolRegistry | None = None
        self.tool_executor: AsyncToolExecutor | None = None
        self._pending_tool_messages: dict[str, str] = {}
        self.tool_parser = ToolIntentParser()
        self.plugin_host: PluginHost | None = None
        self.plugin_dispatcher: AsyncPluginDispatcher | None = None
        if self.runtime.repository is not None:
            self.tool_registry = ToolRegistry()
            register_core_tools(
                self.tool_registry,
                CoreToolServices(
                    self.runtime.repository,
                    clipboard_reader=lambda: QApplication.clipboard().text(),
                    application_opener=open_allowed_application,
                ),
            )
            self.tool_executor = AsyncToolExecutor(self.paths.database, self.permissions)
            self.tool_executor.finished.connect(self._on_tool_result)
            self.plugin_host = PluginHost(self.permissions, self.runtime.repository)
            plugin_root = default_plugin_directory().resolve()
            if plugin_root.is_dir():
                for directory in sorted(plugin_root.iterdir()):
                    if not directory.is_dir():
                        continue
                    try:
                        self.plugin_host.add(
                            PluginManifest.load(directory, trusted_builtin_root=plugin_root)
                        )
                    except Exception as exc:
                        self.logger.write(
                            "plugin_load_failed",
                            plugin=directory.name,
                            error_type=type(exc).__name__,
                        )
            for manifest in self.plugin_host.manifests():
                if not manifest.builtin or not self.plugin_host.enabled(manifest.name):
                    continue
                subject = f"plugin.{manifest.name}"
                self.permissions.grant(
                    Capability.PLUGIN_EXECUTE,
                    subject=subject,
                    reason="previously enabled bundled plugin",
                )
                for permission in manifest.permissions:
                    self.permissions.grant(
                        permission.capability,
                        subject=subject,
                        scope=dict(permission.scope),
                        reason=f"declared by {manifest.name}",
                    )
            self.plugin_dispatcher = AsyncPluginDispatcher(
                self.paths.database,
                self.permissions,
                self.plugin_host.manifests(),
            )
            self.plugin_dispatcher.finished.connect(self._on_plugin_results)

        self.control_center = CompanionControlCenter(
            self.settings,
            self.runtime.repository,
            self.runtime.memory,
            self.plugin_host,
            self.runtime.state,
        )
        self.control_center.settings_changed.connect(self._apply_settings)
        self.control_center.privacy_changed.connect(self._privacy_changed)
        self.control_center.activity_event.connect(self._dispatch_plugin_event)

        self.update_checker = AsyncUpdateChecker(self.permissions, __version__)
        self.update_checker.finished.connect(self._on_update_checked)

        self.audio_capture = ArecordCapture()
        if config.stt_command:
            try:
                self.stt_provider = CommandSTTProvider(config.stt_command)
            except ValueError:
                self.stt_provider = UnavailableSTTProvider()
        else:
            self.stt_provider = UnavailableSTTProvider()
        self.tts_provider = QtSpeechProvider(self)
        self.tts_provider.finished.connect(self._voice_speech_finished)
        self.tts_provider.failed.connect(self._voice_failed)
        self.audio_state_signal.connect(self._on_audio_state)
        self.audio_partial_signal.connect(self._on_audio_partial)
        self.audio_result_signal.connect(self._on_audio_result)
        self.audio_session = AudioSession(
            self.audio_capture,
            self.stt_provider,
            self.tts_provider,
            self.permissions,
            state_changed=lambda state: self.audio_state_signal.emit(state.value),
            partial_text=self.audio_partial_signal.emit,
        )

        awareness_settings = self._awareness_settings()
        self.awareness = AwarenessService(
            LinuxContextProbe(coding_marker=Path.cwd() / ".vla-pet-coding-status"),
            self.permissions,
            awareness_settings,
        )
        self.proactive_policy = ProactivePolicy()
        self._current_context = DesktopContext(time.time())
        self._last_awareness_at = 0.0
        self._last_task_check_at = 0.0
        self._focus_started_at = 0.0
        self._onboarding: OnboardingWizard | None = None
        self.tray: QSystemTrayIcon | None = None
        self._setup_tray()
        self.notification_monitor = NotificationMonitor(self)
        self.notification_monitor.notification.connect(self._on_notification)
        self.notification_monitor.failed.connect(self._notification_monitor_failed)
        self._stopped = False

        self.ai.start()
        self.logger.write(
            "overlay_start",
            model_id=config.worker.model_id,
            language_model_id=config.worker.language_model_id,
            device=config.worker.device,
            quantization=config.worker.quantization,
            language_quantization=config.worker.language_quantization,
            worker_pid=self.ai.process_id,
            screen_index=screen_index,
            geometry=[geometry.x(), geometry.y(), geometry.width(), geometry.height()],
            desktop_passthrough=True,
            pet_mouse_interactive=True,
            interaction_padding=config.interaction_padding,
            watch_notifications=config.watch_notifications,
            safe_mode=config.safe_mode,
            persist_conversation=config.persist_conversation,
            character_id=self.character.character_id,
        )
        if character_result.fallback_error_code:
            self.logger.write(
                "character_fallback",
                error_code=character_result.fallback_error_code,
                fallback_character_id=self.character.character_id,
            )
            self.bubble = "That character pack was invalid, so I'm using Momo safely."
            self.bubble_until = self.started_at + 8.0
        if self.permissions.permits(Capability.NOTIFICATION_MONITOR_SESSION):
            self.permissions.run_authorized(
                Capability.NOTIFICATION_MONITOR_SESSION,
                self.notification_monitor.start,
            )
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        if (
            not config.skip_onboarding
            and not self.settings.onboarding_completed
            and QGuiApplication.platformName() != "offscreen"
        ):
            QTimer.singleShot(300, self._show_onboarding)
        if self.settings.auto_update_enabled and not config.safe_mode:
            QTimer.singleShot(3000, self._check_for_updates)

    def _awareness_settings(self) -> AwarenessSettings:
        return AwarenessSettings(
            active_window=self.settings.active_window_enabled,
            user_idle=self.settings.idle_detection_enabled,
            system_status=self.settings.system_status_enabled,
            coding_status=self.settings.coding_status_enabled,
            proactive=self.settings.proactive_enabled,
            denied_applications=tuple(self.settings.denied_applications),
            denied_title_fragments=tuple(self.settings.denied_title_fragments),
            quiet_hour_start=self.settings.quiet_hour_start,
            quiet_hour_end=self.settings.quiet_hour_end,
        )

    def _setup_tray(self) -> None:
        if QGuiApplication.platformName() == "offscreen" or not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(QIcon(self.sprites[next(iter(self.sprites))]), self)
        menu = QMenu()
        chat = QAction("Chat", menu)
        settings = QAction("Settings and privacy", menu)
        self._tray_privacy = QAction("Privacy mode", menu)
        self._tray_privacy.setCheckable(True)
        self._tray_privacy.setChecked(self.settings.privacy_mode)
        quit_action = QAction("Quit", menu)
        chat.triggered.connect(self._open_chat)
        settings.triggered.connect(self._open_control_center)
        self._tray_privacy.toggled.connect(self._privacy_changed)
        quit_action.triggered.connect(QApplication.quit)
        for action in (chat, settings, self._tray_privacy, quit_action):
            menu.addAction(action)
        tray.setContextMenu(menu)
        tray.setToolTip(f"{self.character.display_name} desktop companion")
        tray.activated.connect(
            lambda reason: self._open_chat()
            if reason is QSystemTrayIcon.ActivationReason.DoubleClick
            else None
        )
        tray.show()
        self.tray = tray

    def _show_onboarding(self) -> None:
        if self._stopped or self.settings.onboarding_completed:
            return
        self._onboarding = OnboardingWizard(
            self.settings,
            character_name=self.character.display_name,
            model_cache_ready=self.paths.model_cache.exists(),
            model_runtime_ready=(find_spec("torch") is not None and find_spec("transformers") is not None),
            microphone_ready=(
                self.audio_capture.available
                and (
                    not isinstance(self.stt_provider, UnavailableSTTProvider)
                    or bool(self.config.worker.stt_model_id)
                )
            ),
            tts_ready=self.tts_provider.available,
        )
        self._onboarding.finished.connect(self._onboarding_finished)
        self._onboarding.show()
        self._onboarding.raise_()

    def _onboarding_finished(self, _result: int) -> None:
        self.settings.save(self.runtime.repository)
        self._apply_settings(self.settings)
        self._onboarding = None
        if (
            self.settings.onboarding_completed
            and self.settings.ai_enabled
            and not self._base_worker_config.mock_policy
        ):
            self.ai.stop()
            self.ai = AIOrchestrator(self._base_worker_config, self.runtime.bus)
            self.ai.start()
            self.status = "Loading SmolLM + SmolVLM locally…"
            self.next_decision_at = time.monotonic()

    def _open_control_center(self) -> None:
        self.control_center.show_and_refresh()

    def _apply_settings(self, settings: CompanionSettings) -> None:
        self.settings = settings
        self.runtime.memory_enabled = settings.memory_enabled
        self.runtime.state.privacy_mode = settings.privacy_mode
        capabilities = {
            Capability.PERSIST_CONVERSATION: settings.persist_conversation,
            Capability.NOTIFICATION_MONITOR_SESSION: settings.notifications_enabled,
            Capability.MICROPHONE_CAPTURE: settings.voice_enabled,
            Capability.ACTIVE_WINDOW_READ: (
                settings.active_window_enabled or settings.coding_status_enabled
            ),
            Capability.USER_IDLE_READ: settings.idle_detection_enabled,
            Capability.SYSTEM_STATUS_READ: settings.system_status_enabled,
        }
        for capability, enabled in capabilities.items():
            if enabled and capability not in self.permissions.allowed:
                self.permissions.grant(
                    capability,
                    lifetime=PermissionLifetime.SESSION,
                    reason="enabled in companion controls",
                )
            elif not enabled and capability in self.permissions.allowed:
                self.permissions.revoke(capability, subject="core")
        self.awareness.settings = self._awareness_settings()
        self._configure_update_permission()
        if settings.privacy_mode or not settings.notifications_enabled:
            self.notification_monitor.stop()
        elif self.permissions.permits(Capability.NOTIFICATION_MONITOR_SESSION):
            self.notification_monitor.start()
        settings.save(self.runtime.repository)
        if hasattr(self, "_tray_privacy"):
            self._tray_privacy.blockSignals(True)
            self._tray_privacy.setChecked(settings.privacy_mode)
            self._tray_privacy.blockSignals(False)
        self.logger.write(
            "settings_changed",
            memory_enabled=settings.memory_enabled,
            voice_enabled=settings.voice_enabled,
            proactive_enabled=settings.proactive_enabled,
            privacy_mode=settings.privacy_mode,
        )
        if settings.auto_update_enabled:
            QTimer.singleShot(0, self._check_for_updates)

    def _configure_update_permission(self) -> None:
        self.permissions.revoke(Capability.UPDATE_CHECK, subject="core")
        if self.config.safe_mode or not self.settings.auto_update_enabled:
            return
        parsed = urllib.parse.urlparse(self.settings.update_manifest_url)
        if parsed.scheme not in {"file", "https"}:
            return
        self.permissions.grant(
            Capability.UPDATE_CHECK,
            lifetime=PermissionLifetime.SESSION,
            scope={"domain": parsed.hostname or "local-file"},
            reason="opted in to signed release checks",
        )

    def _check_for_updates(self) -> None:
        if (
            self._stopped
            or not self.settings.auto_update_enabled
            or not self.settings.update_manifest_url
            or not self.settings.update_public_key
        ):
            return
        self.update_checker.check(
            self.settings.update_manifest_url,
            self.settings.update_public_key,
            key_id=self.settings.update_key_id,
            channel=self.settings.update_channel,
        )

    def _on_update_checked(self, artifact: object, error: str) -> None:
        if error:
            self.logger.write("update_check", ok=False, error_type=error.split(":", 1)[0])
            return
        if not isinstance(artifact, UpdateArtifact):
            self.logger.write("update_check", ok=True, available=False)
            return
        self.bubble = f"Signed update {artifact.version} is available in {artifact.channel}."
        self.bubble_until = time.monotonic() + 12.0
        self.status = f"Verified update available: {artifact.version}"
        self.logger.write(
            "update_check",
            ok=True,
            available=True,
            version=artifact.version,
            channel=artifact.channel,
        )

    def _privacy_changed(self, enabled: bool) -> None:
        self.settings.privacy_mode = bool(enabled)
        self._apply_settings(self.settings)
        self.bubble = "Privacy mode is on." if enabled else "Optional context can run when enabled."
        self.bubble_until = time.monotonic() + 5.0

    def _toggle_voice(self) -> None:
        if not self.settings.voice_enabled:
            self.bubble = "Enable voice and configure a local STT command in Settings first."
            self.bubble_until = time.monotonic() + 6.0
            return
        if (
            isinstance(self.stt_provider, UnavailableSTTProvider)
            and not self.config.worker.stt_model_id
        ):
            self.bubble = "No local STT provider is configured; text chat is still ready."
            self.bubble_until = time.monotonic() + 7.0
            return
        if self.audio_session.state is AudioState.LISTENING:
            threading.Thread(target=self._finish_voice_background, daemon=True).start()
            return
        if self.audio_session.state is AudioState.SPEAKING:
            self.audio_session.interrupt()
            return
        try:
            self.audio_session.begin_listening(explicit_user_action=True)
        except Exception as exc:
            self._voice_failed(str(exc))

    def _finish_voice_background(self) -> None:
        try:
            if isinstance(self.stt_provider, UnavailableSTTProvider):
                self.audio_result_signal.emit(self.audio_session.capture_for_transcription(), "")
            else:
                self.audio_result_signal.emit(self.audio_session.finish_listening(), "")
        except Exception as exc:
            self.audio_result_signal.emit(None, str(exc))

    def _on_audio_state(self, state: str) -> None:
        self.runtime.state.audio_state = state
        self.runtime.state.listening = state in {"listening", "transcribing"}
        self.runtime.state.speaking = state == "speaking"
        self.chat_dialog.set_audio_state(state)
        labels = {
            "listening": "Listening… click again when finished.",
            "transcribing": "Transcribing locally…",
            "speaking": "Speaking… click the microphone button to interrupt.",
        }
        if state in labels:
            self.bubble = labels[state]
            self.bubble_until = time.monotonic() + 30.0

    def _on_audio_partial(self, text: str) -> None:
        self.chat_dialog.input.setText(text[:500])

    def _on_audio_result(self, turn: object, error: str) -> None:
        if error or turn is None:
            self._voice_failed(error or "Speech could not be transcribed")
            return
        if isinstance(turn, bytes):
            request = AudioTranscription(turn)
            request.validate()
            request_id = self.ai.submit("transcribe", request)
            if request_id is None:
                self._voice_failed("A transcription is already running.")
            else:
                self.status = "Whisper is transcribing locally…"
            return
        transcript = str(getattr(turn, "transcript", "")).strip()
        self.audio_session.reset()
        if transcript:
            self.chat_dialog.accept_voice_transcript(transcript)
            self._submit_chat(transcript)

    def _voice_speech_finished(self) -> None:
        self.audio_session.speech_finished()

    def _voice_failed(self, detail: str) -> None:
        self.audio_session.interrupt()
        self.bubble = detail[:180] or "Voice is unavailable; text chat is still ready."
        self.bubble_until = time.monotonic() + 8.0
        self.logger.write("voice_error", error_type="voice_provider")

    def _cancel_chat(self) -> None:
        self.ai.cancel("chat")
        if self.audio_session.state is AudioState.SPEAKING:
            self.audio_session.interrupt()
        self.bubble = "Cancelled."
        self.bubble_until = time.monotonic() + 3.0

    def _check_context_and_tasks(self, now: float) -> None:
        if now - self._last_awareness_at >= 5.0:
            self._last_awareness_at = now
            focus_seconds = now - self._focus_started_at if self._focus_started_at else 0.0
            self._current_context = self.awareness.sample(
                focus_seconds=focus_seconds,
                privacy_mode=self.settings.privacy_mode,
            )
            reaction = self.proactive_policy.evaluate(
                self._current_context,
                self.awareness.settings,
            )
            if reaction is not None:
                self.bubble = reaction.message
                self.bubble_until = now + 10.0
                self.logger.write(
                    "proactive_reaction",
                    kind=reaction.kind,
                    reason=reaction.reason,
                )
                self.runtime.publish(
                    PlatformEvent(
                        name="proactive.reaction",
                        data={"kind": reaction.kind, "reason": reaction.reason},
                    )
                )
        if now - self._last_task_check_at < 1.0 or self.runtime.repository is None:
            return
        self._last_task_check_at = now
        wall_now = datetime.now(timezone.utc)
        for task in self.runtime.repository.list_tasks(limit=100):
            if task["status"] not in {"open", "active"} or not task["due_at"]:
                continue
            try:
                due = datetime.fromisoformat(task["due_at"])
            except ValueError:
                continue
            if due > wall_now:
                continue
            self.runtime.repository.update_task_status(task["task_id"], "done")
            self.bubble = f"{task['title']} is ready!"
            self.bubble_until = now + 10.0
            if task["kind"] == "pomodoro":
                minutes = int(task["details"].get("minutes", 0))
                self.runtime.life.progression.complete_focus(self.runtime.state, minutes)
                self._focus_started_at = 0.0
            self.logger.write("task_due", kind=task["kind"], task_id=task["task_id"])
            hook = "focus.completed" if task["kind"] == "pomodoro" else "timer.completed"
            self._dispatch_plugin_event(hook, {"kind": task["kind"]})

    def _notification_monitor_failed(self, detail: str) -> None:
        if not self._stopped:
            self.logger.write("notification_monitor_error", detail=detail)

    def _on_notification(self, context: str) -> None:
        if self.settings.privacy_mode:
            return
        now = time.monotonic()
        if context == self.latest_notification and now - self._last_notification_at < 2.0:
            return
        self.latest_notification = context
        self._last_notification_at = now
        self.bubble = "A new notification arrived…"
        self.bubble_until = now + 7.0
        self.logger.write("notification_received", has_body="Message:" in context)
        self.runtime.publish(
            PlatformEvent(name="notification", data={"has_body": "Message:" in context})
        )
        if "notify" not in self.ai.pending_kinds:
            self.ai.submit("notify", NotificationRequest(context))

    def _load_sprites(self, pack: CharacterPack) -> dict[str, QPixmap]:
        sprites: dict[str, QPixmap] = {}
        for spec in pack.animations.values():
            for path in spec.frames:
                pixmap = QPixmap(str(path))
                if pixmap.isNull():
                    raise FileNotFoundError(f"Missing or invalid avatar asset: {path}")
                sprites[str(path)] = pixmap
        return sprites

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(0.1, max(0.0, now - self.last_tick))
        self.last_tick = now
        self._check_context_and_tasks(now)
        idle = self._current_context.user_idle_seconds
        life_decision = self.runtime.tick(
            dt,
            context=LifeContext(
                user_present=idle is None or idle < 300.0,
                user_idle_seconds=idle or 0.0,
                active_application=self._current_context.active_application,
                recent_notification=(now - self._last_notification_at < 30.0),
                focus_active=bool(self._focus_started_at),
            ),
        )
        if life_decision is not None:
            self._life_decision = life_decision
        self.runtime.sync_position(
            self.world.x,
            self.world.y,
            max(1.0, self.world.WIDTH - self.world.PET_WIDTH),
            max(1.0, self.world.FLOOR_Y - self.world.PET_HEIGHT),
        )
        if self.runtime.persistence_enabled and now - self._last_persist_at >= 30.0:
            self.runtime.save()
            self._last_persist_at = now

        if (
            not self.world.is_busy
            and self.world.on_ground
            and not self._dragging
            and self.ai.pending_kinds
        ):
            if abs(self.world.vx) < 1:
                self.world.vx = self.world.facing * 65.0

        facing_before_update = self.world.facing
        was_user_falling = self.world.user_falling
        event = self.world.update(dt)
        if was_user_falling and self.world.on_ground:
            self.bubble = "Soft landing!"
            self.bubble_until = now + 2.5
            # Resume locomotion on the landing frame. Model work may still be
            # finishing, so the local walk animation keeps the pet responsive.
            self.next_decision_at = now
            self.logger.write("mouse_interaction", action="land", x=round(self.world.x, 1))
        if self.world.facing != facing_before_update:
            self.edge_bounced_pending = True
        if event:
            self.logger.write("action_completed", **event.as_dict())
            if (
                event.executed is not ActionKind.WALK
                and event.source not in {"mouse", "fallback", "life"}
                and "narrate" not in self.ai.pending_kinds
            ):
                self.ai.submit("narrate", LanguageNarration(event))
            self.next_decision_at = now + 0.1

        self._handle_responses(now)
        self._request_decision(now)

        if now >= self.bubble_until:
            self.bubble = ""
        if self.ai.timed_out():
            self.status = "SmolVLM timeout; restarting safely"
            self.logger.write("worker_timeout", timeout_s=self.config.worker.timeout_s)
            self.ai.restart()
            self.chat_dialog.set_waiting(False)
        if self.config.max_seconds is not None and now - self.started_at >= self.config.max_seconds:
            QApplication.quit()
        fast_motion = self._dragging or self.world.user_falling or self.world.pose in {
            ActionKind.JUMP,
            ActionKind.THROW,
        }
        target_interval = 16 if fast_motion else 33
        if self.timer.interval() != target_interval:
            self.timer.setInterval(target_interval)
        self._repaint_moving_content()

    def _handle_responses(self, now: float) -> None:
        for response in self.ai.poll():
            if response.kind == "decide":
                expected_sequence = response.metadata.get("sequence_id")
                requested_label = response.metadata.get("requested_action", "")
                requested_action = ActionIntent(requested_label) if requested_label else None
                if self._pending_user_action is not None and requested_action is None:
                    self.logger.write(
                        "decision_superseded",
                        reason="language_action_waiting",
                        requested_action=self._pending_user_action.value,
                    )
                    self.next_decision_at = now
                    continue
                if expected_sequence != self.world.sequence_id or self.world.is_busy:
                    if requested_action is not None:
                        self._pending_user_action = requested_action
                    self.logger.write(
                        "stale_decision",
                        observed_sequence=expected_sequence,
                        current_sequence=self.world.sequence_id,
                        requested_action=requested_label,
                    )
                    continue
                proposed: PetAction = response.payload
                action = self.scheduler.choose(
                    proposed,
                    self.world,
                    now,
                    edge_bounced=self.edge_bounced_pending,
                )
                self.edge_bounced_pending = False
                self.raw_vector = action.raw_vector
                self.world.vx = 0.0
                self.world.apply_action(action)
                self.status = (
                    (
                        f"SmolLM → SmolVLM: {action.kind.value} • {response.latency_s:.2f}s"
                        if requested_action is not None
                        else f"{response.provider}: {action.kind.value} • {response.latency_s:.2f}s"
                    )
                    if response.ok
                    else f"Safe fallback • {response.error}"
                )
                self.logger.write(
                    "decision",
                    ok=response.ok,
                    provider=response.provider,
                    latency_s=round(response.latency_s, 4),
                    error=response.error,
                    action=action.as_dict(),
                    requested_action=requested_label,
                )
            elif response.kind == "narrate":
                self.bubble = str(response.payload)
                self.bubble_until = now + 4.0
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
            elif response.kind == "ask_screen":
                self.bubble = str(response.payload)
                self.bubble_until = now + 12.0
                self.status = (
                    f"{response.provider}: screen answer • {response.latency_s:.2f}s"
                    if response.ok
                    else f"Screen answer fallback • {response.error}"
                )
                self.logger.write(
                    "screen_answer",
                    ok=response.ok,
                    provider=response.provider,
                    latency_s=round(response.latency_s, 4),
                    error=response.error,
                    text=self.bubble,
                )
            elif response.kind == "notify":
                self.bubble = str(response.payload)[:180]
                self.bubble_until = now + 8.0
                self.status = (
                    f"{response.provider}: notification reaction • {response.latency_s:.2f}s"
                    if response.ok
                    else f"Notification fallback • {response.error}"
                )
                self.logger.write(
                    "notification_reaction",
                    ok=response.ok,
                    provider=response.provider,
                    latency_s=round(response.latency_s, 4),
                    error=response.error,
                )
            elif response.kind == "chat":
                result = response.payload
                if not isinstance(result, ChatResult):
                    result = ChatResult(str(result))
                answer = result.reply
                self.chat_dialog.stream_pet_message(answer)
                if self.runtime.persistence_enabled and self.permissions.permits(
                    Capability.PERSIST_CONVERSATION
                ):
                    self.runtime.append_conversation("pet", answer)
                if self.settings.tts_enabled and self.tts_provider.available:
                    self.audio_session.speak(answer)
                self.bubble = answer[:180]
                self.bubble_until = now + 8.0
                if result.requested_action is not None:
                    self._pending_user_action = result.requested_action
                    self.next_decision_at = now
                self.status = (
                    (
                        f"SmolLM requested {result.requested_action.value}; waiting for SmolVLM…"
                        if result.requested_action is not None
                        else f"{response.provider}: chat • {response.latency_s:.2f}s"
                    )
                    if response.ok
                    else f"Chat fallback • {response.error}"
                )
                self.logger.write(
                    "chat_answer",
                    ok=response.ok,
                    provider=response.provider,
                    latency_s=round(response.latency_s, 4),
                    error=response.error,
                    response_chars=len(answer),
                    requested_action=(
                        result.requested_action.value if result.requested_action is not None else ""
                    ),
                )
            elif response.kind == "transcribe":
                if not response.ok:
                    self._voice_failed(
                        "I couldn't transcribe that audio locally. Text chat is still available."
                    )
                    continue
                try:
                    turn = self.audio_session.complete_transcription(
                        str(response.payload),
                        provider=response.provider,
                        audio_bytes=int(response.metadata.get("audio_bytes", 0)),
                    )
                except Exception as exc:
                    self._voice_failed(str(exc))
                    continue
                self.audio_session.reset()
                self.chat_dialog.accept_voice_transcript(turn.transcript)
                self._submit_chat(turn.transcript)

    def _request_decision(self, now: float) -> None:
        if not decision_request_ready(
            world_busy=self.world.is_busy,
            on_ground=self.world.on_ground,
            dragging=self._dragging,
            now=now,
            next_decision_at=self.next_decision_at,
            pending_kinds=self.ai.pending_kinds,
        ):
            return
        if self._pending_user_action is None and now < self.next_cognition_at:
            self._apply_life_action(now)
            return
        requested_action = self._pending_user_action
        observation = self._build_observation(requested_action)
        self.ai.submit("decide", observation)
        self._pending_user_action = None
        if requested_action is None:
            self.next_cognition_at = now + max(5.0, self.config.semantic_interval_s)
        self.status = (
            f"SmolVLM is checking the {requested_action.value} request…"
            if requested_action is not None
            else "SmolVLM is choosing an action…"
        )
        self.logger.write(
            "observation",
            sequence_id=observation.sequence_id,
            state=observation.state,
            requested_action=requested_action.value if requested_action is not None else "",
        )

    def _apply_life_action(self, now: float) -> None:
        intent = self._life_decision.intent if self._life_decision else LifeIntent.WALK
        proposed = self.runtime.life.routine_action(
            intent,
            self._life_routine_step,
            self.world.facing,
        )
        self._life_routine_step += 1
        action = self.scheduler.choose(
            proposed,
            self.world,
            now,
            edge_bounced=self.edge_bounced_pending,
        )
        if proposed.kind not in {ActionKind.WALK, ActionKind.IDLE} and action.kind is ActionKind.WALK:
            # A life-engine special that is cooling down becomes a pause, not
            # another walk. User/model commands keep the scheduler's walk fallback.
            action = PetAction(
                ActionKind.IDLE,
                direction=self.world.facing,
                duration=1.4,
                source="life",
                note=f"{proposed.note}; special cooldown",
            )
        self.edge_bounced_pending = False
        self.world.apply_action(action)
        self.status = f"Life engine: {intent.value}"
        self.logger.write(
            "life_action",
            intent=intent.value,
            action=action.kind.value,
            routine_step=self._life_routine_step - 1,
        )

    def _scaled_sprite(self, kind: ActionKind, height: int | None = None) -> QPixmap:
        target_height = height or self.config.pet_size
        frame_path = self.animation.frame(time.monotonic(), kind)
        flipped = sprite_needs_flip(kind, self.world.facing)
        cache_key = (frame_path, target_height, flipped)
        cached = self._sprite_cache.get(cache_key)
        if cached is not None:
            return cached
        sprite = self.sprites[frame_path].scaledToHeight(
            target_height, Qt.TransformationMode.SmoothTransformation
        )
        if flipped:
            sprite = sprite.transformed(
                QTransform().scale(-1, 1),
                Qt.TransformationMode.SmoothTransformation,
            )
        self._sprite_cache[cache_key] = sprite
        return sprite

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(event.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        sprite, x, y = self._sprite_geometry()
        painter.drawPixmap(x, y, sprite)

        if self.bubble:
            self._paint_bubble(painter, x + sprite.width() // 2, y, self.bubble)
        if self.config.debug:
            self._paint_debug(painter, x, y)
        painter.end()
        if self._shrink_mask_after_paint and not self._pending_mask.isEmpty():
            self._set_overlay_mask(self._pending_mask)
            self._shrink_mask_after_paint = False

    def _repaint_moving_content(self) -> None:
        sprite, sprite_x, sprite_y = self._sprite_geometry()
        current = self._visual_bounds_for(sprite, sprite_x, sprite_y)
        signature = (
            current.width(),
            current.height(),
            self.animation.frame(time.monotonic()),
            self.world.facing,
            self.bubble,
            self.status if self.config.debug else "",
            self.raw_vector if self.config.debug else (),
        )
        moved_x = abs(current.x() - self._last_visual_rect.x())
        moved_y = abs(current.y() - self._last_visual_rect.y())
        if (
            not self._last_visual_rect.isEmpty()
            and moved_x < 4
            and moved_y < 4
            and signature == self._last_render_signature
        ):
            return
        previous_mask = self._pending_mask
        self._last_render_signature = signature
        dirty = self._last_visual_rect.united(current).adjusted(-4, -4, 4, 4)
        self._last_visual_rect = current
        if not dirty.isEmpty():
            desired_mask = self._interaction_region_for(
                sprite,
                sprite_x,
                sprite_y,
                current,
                self.config.interaction_padding,
            )
            required_mask = self._interaction_region_for(
                sprite,
                sprite_x,
                sprite_y,
                current,
                min(24, self.config.interaction_padding),
            )
            mask_context = (bool(self.bubble), self.config.debug)
            can_reuse_mask = (
                not previous_mask.isEmpty()
                and mask_context == self._last_mask_context
                and required_mask.subtracted(previous_mask).isEmpty()
            )
            self._pending_mask = previous_mask if can_reuse_mask else desired_mask
            self._last_mask_context = mask_context
            temporary_mask = self._pending_mask.united(QRegion(dirty))
            if temporary_mask != previous_mask:
                self._set_overlay_mask(temporary_mask)
            # Only shrink after paint when the old drawing lies beyond the new
            # interaction region. Usually padding already contains both frames.
            self._shrink_mask_after_paint = temporary_mask != self._pending_mask
            self.repaint(dirty)

    def _visual_bounds(self) -> QRect:
        sprite, x, y = self._sprite_geometry()
        return self._visual_bounds_for(sprite, x, y)

    def _visual_bounds_for(self, sprite: QPixmap, x: int, y: int) -> QRect:
        bounds = QRect(x, y, sprite.width(), sprite.height())
        if self.bubble:
            bounds = bounds.united(self._bubble_rect(x + sprite.width() // 2, y, self.bubble).toRect())
        if self.config.debug:
            bounds = bounds.united(QRect(max(5, x - 80), max(5, y - 100), 420, 70))
        return bounds

    def _sprite_geometry(self) -> tuple[QPixmap, int, int]:
        loading_walk = not self.world.is_busy and "decide" in self.ai.pending_kinds
        pose = ActionKind.WALK if loading_walk else self.world.pose
        sprite = self._scaled_sprite(pose)
        x = int(self.world.x + self.world.PET_WIDTH / 2 - sprite.width() / 2)
        y = int(self.world.y + self.world.PET_HEIGHT - sprite.height())
        return sprite, x, y

    def _interaction_region(self) -> QRegion:
        sprite, x, y = self._sprite_geometry()
        visual_bounds = self._visual_bounds_for(sprite, x, y)
        return self._interaction_region_for(
            sprite,
            x,
            y,
            visual_bounds,
            self.config.interaction_padding,
        )

    def _interaction_region_for(
        self,
        sprite: QPixmap,
        x: int,
        y: int,
        visual_bounds: QRect,
        padding: int,
    ) -> QRegion:
        pet_rect = QRect(
            x - padding,
            y - padding,
            sprite.width() + padding * 2,
            sprite.height() + padding * 2,
        ).intersected(self.rect())
        # The window mask controls visibility as well as input on Wayland, so
        # speech/debug areas must be included along with the generous pet hitbox.
        return QRegion(pet_rect).united(QRegion(visual_bounds))

    def _update_interaction_mask(self) -> None:
        self._pending_mask = self._interaction_region()
        self._shrink_mask_after_paint = False
        self._last_mask_context = (bool(self.bubble), self.config.debug)
        self._set_overlay_mask(self._pending_mask)

    def _set_overlay_mask(self, region: QRegion) -> None:
        if self._mask_supported:
            self.setMask(region)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        self._interaction_mouse_press(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        self._interaction_mouse_move(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        self._interaction_mouse_release(event)

    def _interaction_mouse_press(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._open_chat()
                event.accept()
                return
            self.world.pick_up()
            self._dragging = True
            self._drag_moved = False
            self._press_global_x = event.globalPosition().x()
            self._press_global_y = event.globalPosition().y()
            self._press_world_x = self.world.x
            self._press_world_y = self.world.y
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._open_control_center()
            else:
                self._ask_about_screen()
            event.accept()
            return

    def _interaction_mouse_move(self, event: QMouseEvent) -> None:
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            delta_x = event.globalPosition().x() - self._press_global_x
            delta_y = event.globalPosition().y() - self._press_global_y
            if abs(delta_x) >= 5 or abs(delta_y) >= 5:
                self._drag_moved = True
            self.world.move_to(self._press_world_x + delta_x, self._press_world_y + delta_y)
            self._repaint_moving_content()
            event.accept()
            return

    def _interaction_mouse_release(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.unsetCursor()
            self.world.drop()
            if not self._drag_moved:
                if self.world.on_ground:
                    self.world.apply_action(
                        PetAction(ActionKind.HAPPY, direction=self.world.facing, duration=0.8, source="mouse")
                    )
                    self.bubble = "Hehe, that tickles!"
                else:
                    self.bubble = "Wheee…"
                self.bubble_until = time.monotonic() + 3.0
                self.logger.write("mouse_interaction", action="pet")
                self.runtime.publish(UserInteractionEvent(name="pet"))
                self._dispatch_plugin_event("pet.interacted", {})
            else:
                self.bubble = "Wheee…" if not self.world.on_ground else "New spot!"
                self.bubble_until = time.monotonic() + 2.0
                self.next_decision_at = time.monotonic() + 0.5
                self.logger.write(
                    "mouse_interaction",
                    action="drop",
                    x=round(self.world.x, 1),
                    y=round(self.world.y, 1),
                )
                self.runtime.publish(UserInteractionEvent(name="drop"))
            event.accept()
            return

    def _open_chat(self) -> None:
        self.chat_dialog.show_and_focus()
        self.runtime.publish(UserInteractionEvent(name="chat_open"))
        self.logger.write("chat_opened")

    def _submit_chat(self, message: str) -> None:
        if "chat" in self.ai.pending_kinds:
            return
        if self.settings.memory_enabled:
            self.runtime.remember_user_message(message)
        invocation = self.tool_parser.parse(message)
        if invocation is not None and self.tool_registry is not None:
            manifest, _handler, scope_builder = self.tool_registry.resolve(invocation.name)
            scope = dict(scope_builder(invocation.arguments))
            if not self.permissions.permits(
                manifest.capability,
                explicit_user_action=invocation.explicit_user_action,
                subject=manifest.subject,
                scope=scope,
            ):
                scope_text = ", ".join(f"{key}={value}" for key, value in scope.items()) or "local data only"
                accepted = QMessageBox.question(
                    self.chat_dialog,
                    "Allow this tool once?",
                    f"{manifest.description}\n\nScope: {scope_text}\n\nThe decision will be recorded without private content.",
                ) is QMessageBox.StandardButton.Yes
                if accepted:
                    self.permissions.grant(
                        manifest.capability,
                        lifetime=PermissionLifetime.ONCE,
                        subject=manifest.subject,
                        scope=scope,
                        reason=f"confirmed tool {manifest.name}",
                    )
            clipboard_text = ""
            if invocation.name == "clipboard.summarize" and self.permissions.permits(
                manifest.capability,
                explicit_user_action=True,
                subject=manifest.subject,
                scope=scope,
            ):
                clipboard_text = QApplication.clipboard().text()
            if self.tool_executor is None or not self.tool_executor.submit(
                invocation, clipboard_text=clipboard_text
            ):
                self.chat_dialog.add_pet_message("A tool is already finishing; please try again.")
                return
            self._pending_tool_messages[invocation.invocation_id] = message
            self.chat_dialog.set_waiting(True)
            self.bubble = f"Using {manifest.description.lower()}…"
            self.bubble_until = time.monotonic() + manifest.timeout_s
            self.status = f"Tool running: {manifest.name}"
            return
        history = self.chat_dialog.history[:-1]
        memory_context = self.runtime.memory_context(message) if self.settings.memory_enabled else ""
        request = ChatRequest(message=message, history=history, memory_context=memory_context)
        request.validate()
        self.ai.submit("chat", request)
        if self.runtime.persistence_enabled and self.permissions.permits(
            Capability.PERSIST_CONVERSATION
        ):
            self.runtime.append_conversation("user", message)
        self.bubble = "Hmm, let me think…"
        self.bubble_until = time.monotonic() + self.config.worker.timeout_s
        self.status = "SmolLM is chatting…"
        self.logger.write("chat_question", message_chars=len(message), history_turns=len(history))

    def _on_tool_result(self, invocation: object, result: object) -> None:
        from vla_pet.tool_runtime import ToolInvocation, ToolResult

        if not isinstance(invocation, ToolInvocation) or not isinstance(result, ToolResult):
            return
        message = self._pending_tool_messages.pop(invocation.invocation_id, "")
        self.chat_dialog.stream_pet_message(result.summary)
        if (
            message
            and self.runtime.persistence_enabled
            and self.permissions.permits(Capability.PERSIST_CONVERSATION)
        ):
            self.runtime.append_conversation("user", message)
            self.runtime.append_conversation("pet", result.summary)
        if self.settings.tts_enabled and self.tts_provider.available:
            self.audio_session.speak(result.summary)
        self.bubble = result.summary[:180]
        self.bubble_until = time.monotonic() + 8.0
        self.status = "Tool finished" if result.ok else f"Tool refused: {result.error_code}"
        if result.ok and invocation.name == "focus.start":
            self._focus_started_at = time.monotonic()
        if result.ok and invocation.name in {"focus.start", "timer.start"}:
            self._dispatch_plugin_event("timer.started", {"kind": invocation.name})
        if result.ok and self.settings.memory_enabled and self.runtime.memory is not None:
            self.runtime.memory.remember_procedure(
                f"Successful companion workflow: {invocation.name}"
            )
        self.logger.write(
            "tool_result",
            tool_name=invocation.name,
            ok=result.ok,
            error_code=result.error_code,
            duration_ms=round(result.duration_ms, 2),
        )

    def _dispatch_plugin_event(self, hook: str, payload: object) -> None:
        if self.plugin_dispatcher is not None and not self.config.safe_mode:
            self.plugin_dispatcher.dispatch(hook, payload if isinstance(payload, dict) else {})

    def _on_plugin_results(self, hook: str, results: object) -> None:
        if not isinstance(results, tuple):
            return
        for result in results:
            if not isinstance(result, dict):
                continue
            self.logger.write(
                "plugin_hook",
                hook=hook,
                plugin=str(result.get("plugin", "")),
                ok=bool(result.get("ok", False)),
                error_type=str(result.get("error", "")),
            )
            message = str(result.get("message", ""))
            if message:
                self.bubble = message[:180]
                self.bubble_until = time.monotonic() + 5.0

    def _ask_about_screen(self) -> None:
        if self.settings.privacy_mode:
            self.bubble = "Privacy mode is on; screen capture stayed off."
            self.bubble_until = time.monotonic() + 5.0
            return
        if not self.permissions.permits(
            Capability.SCREEN_CAPTURE_EACH_TIME,
            explicit_user_action=True,
        ):
            self.bubble = "Screen access is disabled in safe mode."
            self.bubble_until = time.monotonic() + 5.0
            return
        if "ask_screen" in self.ai.pending_kinds:
            self.bubble = "I'm still looking at the previous question…"
            self.bubble_until = time.monotonic() + 4.0
            return
        question, accepted = QInputDialog.getText(
            self,
            "Ask SmolVLM about the screen",
            "What should I look for?",
            QLineEdit.EchoMode.Normal,
            "What is visible on my screen?",
        )
        if accepted and question.strip():
            self._submit_screen_question(question.strip(), notification_context=self.latest_notification)

    def _submit_screen_question(self, question: str, *, notification_context: str = "") -> None:
        if not self.permissions.permits(
            Capability.SCREEN_CAPTURE_EACH_TIME,
            explicit_user_action=True,
        ):
            self.bubble = "Screen access is disabled in safe mode."
            self.bubble_until = time.monotonic() + 5.0
            return
        self._pending_screen_question = (question, notification_context)
        self.bubble = "Please approve the screenshot request…"
        self.bubble_until = time.monotonic() + 60.0
        started = self.permissions.run_authorized(
            Capability.SCREEN_CAPTURE_EACH_TIME,
            self.screen_capture.request,
            explicit_user_action=True,
        )
        if not started and self._pending_screen_question is not None:
            self._pending_screen_question = None
            self.bubble = "A screenshot request is already active."
            self.bubble_until = time.monotonic() + 5.0

    def _on_screen_capture(self, screenshot: np.ndarray | None, error: str) -> None:
        pending = self._pending_screen_question
        self._pending_screen_question = None
        if error or screenshot is None:
            self.bubble = error or "I couldn't capture this screen."
            self.bubble_until = time.monotonic() + 8.0
            self.logger.write("screen_capture_failed", error=self.bubble)
            return
        if not pending:
            return
        question, notification_context = pending
        self._submit_captured_question(screenshot, question, notification_context)

    def _submit_captured_question(
        self,
        screenshot: np.ndarray,
        question: str,
        notification_context: str,
    ) -> None:
        request = VisualQuestion(screenshot, question, notification_context)
        request.validate()
        self.ai.submit("ask_screen", request)
        self.bubble = "Let me look…"
        self.bubble_until = time.monotonic() + self.config.worker.timeout_s
        self.status = "SmolVLM is inspecting the captured screen…"
        self.logger.write(
            "screen_question",
            image_size=[screenshot.shape[1], screenshot.shape[0]],
            has_notification=bool(notification_context),
        )

    def _paint_bubble(self, painter: QPainter, center_x: int, pet_y: int, text: str) -> None:
        bubble = self._bubble_pixmap(text)
        rect = self._bubble_rect(center_x, pet_y, text)
        painter.drawPixmap(int(rect.x()), int(rect.y()), bubble)

    def _paint_debug(self, painter: QPainter, pet_x: int, pet_y: int) -> None:
        text = f"{self.status}\nx={self.world.x:.0f}  v={self.world.vx:.0f}  raw={self.raw_vector[:4]}"
        rect = QRectF(max(5, pet_x - 80), max(5, pet_y - 100), 420, 70)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(10, 14, 23, 205))
        painter.drawRoundedRect(rect, 8, 8)
        painter.setPen(QColor(188, 224, 211))
        painter.setFont(QFont("Monospace", 9))
        painter.drawText(rect.adjusted(10, 8, -10, -8), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, text)

    def _bubble_rect(self, center_x: int, pet_y: int, text: str) -> QRectF:
        bubble = self._bubble_pixmap(text)
        width, height = bubble.width(), bubble.height()
        x = max(8, min(self.width() - width - 8, center_x - width // 2))
        y = max(8, pet_y - height - 14)
        return QRectF(x, y, width, height)

    def _bubble_pixmap(self, text: str) -> QPixmap:
        bounded = text[:180]
        cached = self._bubble_cache.get(bounded)
        if cached is not None:
            return cached
        font = QFont("Sans Serif", 11)
        metrics = QFontMetrics(font)
        text_width = metrics.horizontalAdvance(bounded)
        width = min(340, max(170, text_width + 30))
        line_count = 1 if text_width < width - 28 else 2
        height = 38 + line_count * 18
        bubble = QPixmap(width, height)
        bubble.fill(Qt.GlobalColor.transparent)
        painter = QPainter(bubble)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(font)
        painter.setPen(QPen(QColor(116, 78, 67), 2))
        painter.setBrush(QColor(255, 247, 225, 245))
        painter.drawRoundedRect(QRectF(1, 1, width - 2, height - 2), 14, 14)
        painter.setPen(QColor(42, 39, 51))
        painter.drawText(
            QRectF(14, 8, width - 28, height - 16),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            bounded,
        )
        painter.end()
        if len(self._bubble_cache) >= 32:
            self._bubble_cache.pop(next(iter(self._bubble_cache)))
        self._bubble_cache[bounded] = bubble
        return bubble

    def _build_observation(
        self, requested_action: ActionIntent | None = None
    ) -> SandboxObservation:
        scene = QImage(QSize(256, 256), QImage.Format.Format_RGB888)
        scene.fill(QColor(24, 29, 42))
        painter = QPainter(scene)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setPen(QPen(QColor(105, 110, 126), 2))
        painter.drawLine(0, 225, 256, 225)
        sprite = self._scaled_sprite(ActionKind.WALK, height=94)
        available = max(1.0, self.world.WIDTH - self.world.PET_WIDTH)
        x = int((self.world.x / available) * max(1, 256 - sprite.width()))
        painter.drawPixmap(x, 225 - sprite.height(), sprite)
        painter.end()

        full_array = self._qimage_to_chw(scene)
        observation = SandboxObservation(
            sequence_id=self.world.sequence_id,
            images={"observation.image": full_array},
            state=self.world.normalized_state(),
            task=OVERLAY_TASK_PROMPT,
            requested_action=requested_action,
        )
        observation.validate()
        return observation

    @staticmethod
    def _qimage_to_chw(image: QImage) -> np.ndarray:
        converted = image.convertToFormat(QImage.Format.Format_RGB888)
        width, height = converted.width(), converted.height()
        bytes_per_line = converted.bytesPerLine()
        raw = np.frombuffer(converted.bits(), dtype=np.uint8, count=height * bytes_per_line)
        rgb = raw.reshape(height, bytes_per_line)[:, : width * 3].reshape(height, width, 3).copy()
        return np.ascontiguousarray(np.transpose(rgb, (2, 0, 1)), dtype=np.float32) / 255.0

    def shutdown(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self.timer.stop()
        self.notification_monitor.stop()
        self.chat_dialog.hide()
        self.control_center.hide()
        if self._onboarding is not None:
            self._onboarding.close()
            self._onboarding = None
        self.audio_session.interrupt()
        if self.tool_executor is not None:
            self.tool_executor.close()
        if self.plugin_dispatcher is not None:
            self.plugin_dispatcher.close()
        self.update_checker.close()
        if self.tray is not None:
            self.tray.hide()
        self.ai.stop()
        self.runtime.sync_position(
            self.world.x,
            self.world.y,
            max(1.0, self.world.WIDTH - self.world.PET_WIDTH),
            max(1.0, self.world.FLOOR_Y - self.world.PET_HEIGHT),
        )
        self.runtime.close()
        self.logger.write("overlay_end")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.shutdown()
        super().closeEvent(event)


def run_overlay(config: OverlayConfig) -> int:
    lock_path = Path(tempfile.gettempdir()) / (
        f"vla-pet-{os.getuid()}-screen-{config.screen_index}.lock"
    )
    process_lock = QLockFile(str(lock_path))
    process_lock.setStaleLockTime(5_000)
    if not process_lock.tryLock(100):
        print(
            f"A desktop pet is already running on screen {config.screen_index}.",
            file=sys.stderr,
        )
        return 2
    app = QApplication.instance() or QApplication([])
    try:
        app.setQuitOnLastWindowClosed(True)
        overlay = DesktopPetOverlay(config)
        app.aboutToQuit.connect(overlay.shutdown)
        signal.signal(signal.SIGINT, lambda *_: app.quit())
        overlay._update_interaction_mask()
        overlay.show()
        overlay.raise_()
        QTimer.singleShot(0, overlay.raise_)
        return app.exec()
    finally:
        process_lock.unlock()
