from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from vla_pet.theme import apply_companion_theme


class PetChatDialog(QDialog):
    message_submitted = Signal(str)
    cancel_requested = Signal()
    settings_requested = Signal()
    voice_requested = Signal()
    stream_finished = Signal(str)

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setWindowTitle("Chat with your desktop pet")
        self.resize(420, 360)
        self._history: list[tuple[str, str]] = []

        title = QLabel("Chat with SmolLM")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setPlaceholderText("Your pet is listening…")
        self.input = QLineEdit()
        self.input.setPlaceholderText("Say something…")
        self.input.setMaxLength(500)
        self.send = QPushButton("Send")
        self.cancel = QPushButton("Cancel")
        self.cancel.setEnabled(False)
        self.voice = QPushButton("Push to talk")
        self.settings = QPushButton("Settings")

        row = QHBoxLayout()
        row.addWidget(self.input, 1)
        row.addWidget(self.send)
        row.addWidget(self.cancel)
        controls = QHBoxLayout()
        controls.addWidget(self.voice)
        controls.addWidget(self.settings)
        controls.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self.transcript, 1)
        layout.addLayout(controls)
        layout.addLayout(row)

        self.send.clicked.connect(self._submit)
        self.input.returnPressed.connect(self._submit)
        self.cancel.clicked.connect(self._cancel)
        self.voice.clicked.connect(self.voice_requested)
        self.settings.clicked.connect(self.settings_requested)
        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(35)
        self._stream_timer.timeout.connect(self._stream_step)
        self._stream_parts: list[str] = []
        self._stream_index = 0
        apply_companion_theme(self)

    @property
    def history(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._history[-12:])

    def _submit(self) -> None:
        message = self.input.text().strip()
        if not message or not self.input.isEnabled():
            return
        self._append("user", message)
        self.input.clear()
        self.set_waiting(True)
        self.message_submitted.emit(message)

    def accept_voice_transcript(self, message: str) -> None:
        value = " ".join(message.strip().split())[:500]
        if not value:
            return
        self._append("user", value)
        self.set_waiting(True)

    def add_pet_message(self, text: str) -> None:
        self._stream_timer.stop()
        self._append("pet", text)
        self.set_waiting(False)

    def stream_pet_message(self, text: str) -> None:
        self._stream_timer.stop()
        self._stream_parts = text.split()
        self._stream_index = 0
        if not self._stream_parts:
            self.set_waiting(False)
            return
        self._stream_timer.start()

    def _stream_step(self) -> None:
        self._stream_index = min(len(self._stream_parts), self._stream_index + 1)
        self._render(stream_text=" ".join(self._stream_parts[: self._stream_index]))
        if self._stream_index >= len(self._stream_parts):
            self._stream_timer.stop()
            text = " ".join(self._stream_parts)
            self._history.append(("pet", text))
            self._stream_parts = []
            self._stream_index = 0
            self._render()
            self.set_waiting(False)
            self.stream_finished.emit(text)

    def restore_history(self, history: tuple[tuple[str, str], ...]) -> None:
        self._history.clear()
        self.transcript.clear()
        for role, text in history[-12:]:
            if role in {"user", "pet"} and text:
                self._append(role, text)

    def _append(self, role: str, text: str) -> None:
        self._history.append((role, text))
        self._render()

    def _render(self, *, stream_text: str = "") -> None:
        parts: list[str] = []
        for role, text in self._history:
            parts.append(self._html_turn(role, text))
        if stream_text:
            parts.append(self._html_turn("pet", stream_text + "▌"))
        self.transcript.setHtml("".join(parts))
        self.transcript.moveCursor(QTextCursor.MoveOperation.End)

    @staticmethod
    def _html_turn(role: str, text: str) -> str:
        name = "You" if role == "user" else "Pet"
        color = "#5b5bd6" if role == "user" else "#b04b67"
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f'<p><b style="color:{color}">{name}:</b> {escaped}</p>'

    def set_waiting(self, waiting: bool) -> None:
        self.input.setEnabled(not waiting)
        self.send.setEnabled(not waiting)
        self.cancel.setEnabled(waiting or self._stream_timer.isActive())
        self.send.setText("Thinking…" if waiting else "Send")
        if not waiting:
            self.input.setFocus()

    def set_audio_state(self, state: str) -> None:
        labels = {
            "listening": "Stop listening",
            "transcribing": "Transcribing…",
            "thinking": "Thinking…",
            "speaking": "Stop speaking",
        }
        self.voice.setText(labels.get(state, "Push to talk"))
        self.voice.setEnabled(state not in {"transcribing", "thinking"})

    def _cancel(self) -> None:
        self._stream_timer.stop()
        self._stream_parts = []
        self._stream_index = 0
        self._render()
        self.set_waiting(False)
        self.cancel_requested.emit()

    def show_and_focus(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        # Keep the in-memory conversation when the user closes and reopens it.
        self.hide()
        event.ignore()
