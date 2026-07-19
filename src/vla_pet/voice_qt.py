from __future__ import annotations

from collections import deque

from PySide6.QtCore import QObject, Signal
from PySide6.QtTextToSpeech import QTextToSpeech


class QtSpeechProvider(QObject):
    """Sentence-queue TTS that accepts chunks and supports immediate interruption."""

    finished = Signal()
    failed = Signal(str)

    name = "qt-speechd"

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.engine = QTextToSpeech(self)
        self._queue: deque[str] = deque()
        self._active = False
        self.engine.stateChanged.connect(self._state_changed)

    @property
    def available(self) -> bool:
        return bool(QTextToSpeech.availableEngines())

    def speak(self, text: str) -> None:
        value = " ".join(text.strip().split())
        if not value:
            return
        self._queue.append(value)
        if not self._active:
            self._speak_next()

    def stop(self) -> None:
        self._queue.clear()
        self.engine.stop()
        self._active = False

    def _speak_next(self) -> None:
        if not self._queue:
            self._active = False
            self.finished.emit()
            return
        self._active = True
        self.engine.say(self._queue.popleft())

    def _state_changed(self, state: QTextToSpeech.State) -> None:
        if state is QTextToSpeech.State.Ready and self._active:
            self._speak_next()
        elif state is QTextToSpeech.State.Error:
            self._queue.clear()
            self._active = False
            self.failed.emit(self.engine.errorString())
