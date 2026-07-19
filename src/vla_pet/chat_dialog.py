from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


class PetChatDialog(QDialog):
    message_submitted = Signal(str)

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

        row = QHBoxLayout()
        row.addWidget(self.input, 1)
        row.addWidget(self.send)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self.transcript, 1)
        layout.addLayout(row)

        self.send.clicked.connect(self._submit)
        self.input.returnPressed.connect(self._submit)

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

    def add_pet_message(self, text: str) -> None:
        self._append("pet", text)
        self.set_waiting(False)

    def _append(self, role: str, text: str) -> None:
        self._history.append((role, text))
        name = "You" if role == "user" else "Pet"
        color = "#5b5bd6" if role == "user" else "#b04b67"
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.transcript.append(f'<p><b style="color:{color}">{name}:</b> {escaped}</p>')

    def set_waiting(self, waiting: bool) -> None:
        self.input.setEnabled(not waiting)
        self.send.setEnabled(not waiting)
        self.send.setText("Thinking…" if waiting else "Send")
        if not waiting:
            self.input.setFocus()

    def show_and_focus(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        # Keep the in-memory conversation when the user closes and reopens it.
        self.hide()
        event.ignore()
