from __future__ import annotations

import signal
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QLockFile, QProcess, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QRegion,
    QTransform,
)
from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit, QWidget

from vla_pet.chat_dialog import PetChatDialog
from vla_pet.contracts import (
    ActionIntent,
    ActionKind,
    ChatRequest,
    ChatResult,
    LanguageNarration,
    PetAction,
    SandboxObservation,
    VisualQuestion,
)
from vla_pet.notifications import decode_dbus_string, notification_from_strings
from vla_pet.overlay_actions import OverlayActionScheduler, sprite_needs_flip
from vla_pet.screen_capture import PortalScreenshot
from vla_pet.session_log import SessionLogger
from vla_pet.worker import AIWorkerClient, WorkerConfig
from vla_pet.world import PetWorld


POSE_FILES = {
    ActionKind.IDLE: "idle.png",
    ActionKind.WALK: "walking.png",
    ActionKind.JUMP: "jumping.png",
    ActionKind.THROW: "throw.png",
    ActionKind.HAPPY: "happy.png",
    ActionKind.SAD: "sad.png",
}

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


def default_asset_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "animations"


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


class DesktopPetOverlay(QWidget):
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
        self.scheduler = OverlayActionScheduler()
        self.edge_bounced_pending = False
        self.sprites = self._load_sprites(config.asset_directory or default_asset_directory())
        self.worker = AIWorkerClient(config.worker)
        self.logger = SessionLogger(enabled=config.logging)
        self.started_at = time.monotonic()
        self.last_tick = self.started_at
        self.next_decision_at = 0.0
        self.bubble = "Drag me anywhere. Ctrl+click to chat. Right-click to inspect the screen."
        self.bubble_until = self.started_at + 9.0
        self.status = "Loading SmolVLM on CPU…"
        self.raw_vector: tuple[float, ...] = ()
        self.latest_notification = ""
        self._last_notification_at = 0.0
        self.portal_screenshot = PortalScreenshot(self)
        self.portal_screenshot.finished.connect(self._on_portal_screenshot)
        self._pending_screen_question: tuple[str, str] | None = None
        self._pending_user_action: ActionIntent | None = None
        self._dragging = False
        self._drag_moved = False
        self._press_global_x = 0.0
        self._press_global_y = 0.0
        self._press_world_x = 0.0
        self._press_world_y = 0.0
        self._last_visual_rect = QRect()
        self._pending_mask = QRegion()
        self._mask_supported = QGuiApplication.platformName() != "offscreen"
        self.chat_dialog = PetChatDialog()
        self.chat_dialog.message_submitted.connect(self._submit_chat)
        self._notification_process: QProcess | None = None
        self._dbus_line_buffer = ""
        self._notification_strings: list[str] = []
        self._notification_delivered = False
        self._stopped = False

        self.worker.start()
        self.logger.write(
            "overlay_start",
            model_id=config.worker.model_id,
            language_model_id=config.worker.language_model_id,
            device=config.worker.device,
            quantization=config.worker.quantization,
            language_quantization=config.worker.language_quantization,
            worker_pid=self.worker.process_id,
            screen_index=screen_index,
            geometry=[geometry.x(), geometry.y(), geometry.width(), geometry.height()],
            desktop_passthrough=True,
            pet_mouse_interactive=True,
            interaction_padding=config.interaction_padding,
            watch_notifications=config.watch_notifications,
        )
        if config.watch_notifications:
            self._start_notification_monitor()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _start_notification_monitor(self) -> None:
        process = QProcess(self)
        process.setProgram("dbus-monitor")
        process.setArguments(
            [
                "--session",
                "type='method_call',interface='org.freedesktop.Notifications',member='Notify'",
            ]
        )
        process.readyReadStandardOutput.connect(self._read_notification_output)
        process.errorOccurred.connect(lambda _error: self._notification_monitor_failed(process))
        process.start()
        self._notification_process = process

    def _notification_monitor_failed(self, process: QProcess) -> None:
        if not self._stopped:
            self.logger.write("notification_monitor_error", detail=process.errorString())

    def _read_notification_output(self) -> None:
        if not self._notification_process:
            return
        chunk = bytes(self._notification_process.readAllStandardOutput()).decode("utf-8", "replace")
        self._dbus_line_buffer += chunk
        lines = self._dbus_line_buffer.split("\n")
        self._dbus_line_buffer = lines.pop()
        for line in lines:
            if line.startswith("method call"):
                self._notification_strings = []
                self._notification_delivered = False
                continue
            value = decode_dbus_string(line)
            if value is not None and not self._notification_delivered:
                self._notification_strings.append(value)
                notification = notification_from_strings(self._notification_strings)
                if notification:
                    self._notification_delivered = True
                    self._on_notification(notification.context)

    def _on_notification(self, context: str) -> None:
        now = time.monotonic()
        if context == self.latest_notification and now - self._last_notification_at < 2.0:
            return
        self.latest_notification = context
        self._last_notification_at = now
        self.bubble = context[:180]
        self.bubble_until = now + 7.0
        self.logger.write("notification_received", has_body="Message:" in context)
        if (
            "ask_screen" not in self.worker.pending_kinds
            and not self.portal_screenshot.active
            and self._pending_screen_question is None
        ):
            self._submit_screen_question(
                "Explain this new notification briefly and tell me if it needs attention.",
                notification_context=context,
            )

    def _load_sprites(self, directory: Path) -> dict[ActionKind, QPixmap]:
        sprites = {}
        for kind, filename in POSE_FILES.items():
            path = directory / filename
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                raise FileNotFoundError(f"Missing or invalid avatar asset: {path}")
            sprites[kind] = pixmap
        return sprites

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(0.1, max(0.0, now - self.last_tick))
        self.last_tick = now

        if (
            not self.world.is_busy
            and self.world.on_ground
            and not self._dragging
            and self.worker.pending_kinds
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
                and event.source not in {"mouse", "fallback"}
                and "narrate" not in self.worker.pending_kinds
            ):
                self.worker.submit("narrate", LanguageNarration(event))
            self.next_decision_at = now + 0.1

        self._handle_responses(now)
        self._request_decision(now)

        if now >= self.bubble_until:
            self.bubble = ""
        if self.worker.timed_out():
            self.status = "SmolVLM timeout; restarting safely"
            self.logger.write("worker_timeout", timeout_s=self.config.worker.timeout_s)
            self.worker.stop()
            self.worker = AIWorkerClient(self.config.worker)
            self.worker.start()
            self.chat_dialog.set_waiting(False)
        if self.config.max_seconds is not None and now - self.started_at >= self.config.max_seconds:
            QApplication.quit()
        self._repaint_moving_content()
        self._update_interaction_mask()

    def _handle_responses(self, now: float) -> None:
        for response in self.worker.poll():
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
            elif response.kind == "chat":
                result = response.payload
                if not isinstance(result, ChatResult):
                    result = ChatResult(str(result))
                answer = result.reply
                self.chat_dialog.add_pet_message(answer)
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

    def _request_decision(self, now: float) -> None:
        if not decision_request_ready(
            world_busy=self.world.is_busy,
            on_ground=self.world.on_ground,
            dragging=self._dragging,
            now=now,
            next_decision_at=self.next_decision_at,
            pending_kinds=self.worker.pending_kinds,
        ):
            return
        requested_action = self._pending_user_action
        observation = self._build_observation(requested_action)
        self.worker.submit("decide", observation)
        self._pending_user_action = None
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

    def _scaled_sprite(self, kind: ActionKind, height: int | None = None) -> QPixmap:
        target_height = height or self.config.pet_size
        sprite = self.sprites[kind].scaledToHeight(target_height, Qt.TransformationMode.SmoothTransformation)
        if sprite_needs_flip(kind, self.world.facing):
            sprite = sprite.transformed(QTransform().scale(-1, 1), Qt.TransformationMode.SmoothTransformation)
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
        if not self._pending_mask.isEmpty():
            self._set_overlay_mask(self._pending_mask)

    def _repaint_moving_content(self) -> None:
        current = self._visual_bounds()
        dirty = self._last_visual_rect.united(current).adjusted(-4, -4, 4, 4)
        self._last_visual_rect = current
        if not dirty.isEmpty():
            self._pending_mask = self._interaction_region()
            # Temporarily expose both the old and new drawing areas, clear them
            # synchronously, then paintEvent shrinks the mask to the current pet.
            self._set_overlay_mask(self._pending_mask.united(QRegion(dirty)))
            self.repaint(dirty)

    def _visual_bounds(self) -> QRect:
        sprite, x, y = self._sprite_geometry()
        bounds = QRect(x, y, sprite.width(), sprite.height())
        if self.bubble:
            bounds = bounds.united(self._bubble_rect(x + sprite.width() // 2, y, self.bubble).toRect())
        if self.config.debug:
            bounds = bounds.united(QRect(max(5, x - 80), max(5, y - 100), 420, 70))
        return bounds

    def _sprite_geometry(self) -> tuple[QPixmap, int, int]:
        loading_walk = not self.world.is_busy and "decide" in self.worker.pending_kinds
        pose = ActionKind.WALK if loading_walk else self.world.pose
        sprite = self._scaled_sprite(pose)
        x = int(self.world.x + self.world.PET_WIDTH / 2 - sprite.width() / 2)
        y = int(self.world.y + self.world.PET_HEIGHT - sprite.height())
        return sprite, x, y

    def _interaction_region(self) -> QRegion:
        sprite, x, y = self._sprite_geometry()
        padding = self.config.interaction_padding
        pet_rect = QRect(
            x - padding,
            y - padding,
            sprite.width() + padding * 2,
            sprite.height() + padding * 2,
        ).intersected(self.rect())
        # The window mask controls visibility as well as input on Wayland, so
        # speech/debug areas must be included along with the generous pet hitbox.
        return QRegion(pet_rect).united(QRegion(self._visual_bounds()))

    def _update_interaction_mask(self) -> None:
        self._pending_mask = self._interaction_region()
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
            event.accept()
            return

    def _open_chat(self) -> None:
        self.chat_dialog.show_and_focus()
        self.logger.write("chat_opened")

    def _submit_chat(self, message: str) -> None:
        if "chat" in self.worker.pending_kinds:
            return
        history = self.chat_dialog.history[:-1]
        request = ChatRequest(message=message, history=history)
        request.validate()
        self.worker.submit("chat", request)
        self.bubble = "Hmm, let me think…"
        self.bubble_until = time.monotonic() + self.config.worker.timeout_s
        self.status = "SmolLM is chatting…"
        self.logger.write("chat_question", message_chars=len(message), history_turns=len(history))

    def _ask_about_screen(self) -> None:
        if "ask_screen" in self.worker.pending_kinds:
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
        screenshot = self._capture_screen()
        if screenshot is None:
            self._pending_screen_question = (question, notification_context)
            self.bubble = "Please approve the GNOME screenshot request…"
            self.bubble_until = time.monotonic() + 60.0
            if not self.portal_screenshot.request():
                self._pending_screen_question = None
            return
        self._submit_captured_question(screenshot, question, notification_context)

    def _on_portal_screenshot(self, image: QImage | None, error: str) -> None:
        pending = self._pending_screen_question
        self._pending_screen_question = None
        if error or image is None:
            self.bubble = error or "I couldn't capture this screen."
            self.bubble_until = time.monotonic() + 8.0
            self.logger.write("screen_capture_failed", error=self.bubble)
            return
        if not pending:
            return
        screenshot = self._image_to_rgb(image)
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
        self.worker.submit("ask_screen", request)
        self.bubble = "Let me look…"
        self.bubble_until = time.monotonic() + self.config.worker.timeout_s
        self.status = "SmolVLM is inspecting the captured screen…"
        self.logger.write(
            "screen_question",
            image_size=[screenshot.shape[1], screenshot.shape[0]],
            has_notification=bool(notification_context),
        )

    def _capture_screen(self) -> np.ndarray | None:
        pixmap = self.screen.grabWindow(0)
        if pixmap.isNull():
            return None
        return self._image_to_rgb(pixmap.toImage())

    @staticmethod
    def _image_to_rgb(image: QImage) -> np.ndarray:
        image = image.scaled(
            QSize(768, 768),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        converted = image.convertToFormat(QImage.Format.Format_RGB888)
        width, height = converted.width(), converted.height()
        bytes_per_line = converted.bytesPerLine()
        raw = np.frombuffer(converted.bits(), dtype=np.uint8, count=height * bytes_per_line)
        return raw.reshape(height, bytes_per_line)[:, : width * 3].reshape(height, width, 3).copy()

    def _paint_bubble(self, painter: QPainter, center_x: int, pet_y: int, text: str) -> None:
        font = QFont("Sans Serif", 11)
        painter.setFont(font)
        bounded = text[:180]
        rect = self._bubble_rect(center_x, pet_y, bounded)
        painter.setPen(QPen(QColor(116, 78, 67), 2))
        painter.setBrush(QColor(255, 247, 225, 245))
        painter.drawRoundedRect(rect, 14, 14)
        painter.setPen(QColor(42, 39, 51))
        painter.drawText(rect.adjusted(14, 8, -14, -8), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, bounded)

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
        metrics = QFontMetrics(QFont("Sans Serif", 11))
        bounded = text[:180]
        width = min(340, max(170, metrics.horizontalAdvance(bounded) + 30))
        line_count = 1 if metrics.horizontalAdvance(bounded) < width - 28 else 2
        height = 38 + line_count * 18
        x = max(8, min(self.width() - width - 8, center_x - width // 2))
        y = max(8, pet_y - height - 14)
        return QRectF(x, y, width, height)

    def _build_observation(
        self, requested_action: ActionIntent | None = None
    ) -> SandboxObservation:
        scene = QImage(QSize(256, 256), QImage.Format.Format_RGB888)
        scene.fill(QColor(24, 29, 42))
        painter = QPainter(scene)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setPen(QPen(QColor(105, 110, 126), 2))
        painter.drawLine(0, 225, 256, 225)
        sprite = self._scaled_sprite(ActionKind.WALK, 94)
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
        if self._notification_process:
            self._notification_process.terminate()
            self._notification_process.waitForFinished(500)
        self.chat_dialog.hide()
        self.worker.stop()
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
