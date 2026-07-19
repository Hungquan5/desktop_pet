from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from vla_pet.errors import ErrorCategory, PetError
from vla_pet.permissions import Capability, PermissionBroker


class AudioState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    ERROR = "error"


class AudioCapture(Protocol):
    def start(self) -> None: ...

    def stop(self) -> bytes: ...

    def cancel(self) -> None: ...


class STTProvider(Protocol):
    name: str

    def transcribe(self, wave_bytes: bytes) -> Iterable[str]: ...


class TTSProvider(Protocol):
    name: str

    def speak(self, text: str) -> None: ...

    def stop(self) -> None: ...


@dataclass(frozen=True, slots=True)
class VoiceTurn:
    transcript: str
    provider: str
    audio_bytes: int
    elapsed_s: float


class AudioSession:
    """Permission-gated push-to-talk state machine with echo suppression."""

    def __init__(
        self,
        capture: AudioCapture,
        stt: STTProvider,
        tts: TTSProvider,
        broker: PermissionBroker,
        *,
        echo_guard_s: float = 0.35,
        state_changed: Callable[[AudioState], None] | None = None,
        partial_text: Callable[[str], None] | None = None,
    ) -> None:
        self.capture = capture
        self.stt = stt
        self.tts = tts
        self.broker = broker
        self.echo_guard_s = max(0.0, echo_guard_s)
        self.state_changed = state_changed or (lambda _state: None)
        self.partial_text = partial_text or (lambda _text: None)
        self.state = AudioState.IDLE
        self._last_speech_stopped = float("-inf")

    def begin_listening(self, *, explicit_user_action: bool = True) -> None:
        if self.state not in {AudioState.IDLE, AudioState.INTERRUPTED, AudioState.ERROR}:
            raise RuntimeError(f"Cannot listen while audio state is {self.state.value}")
        if time.monotonic() - self._last_speech_stopped < self.echo_guard_s:
            raise PetError(
                ErrorCategory.PERMISSION_DENIED,
                "audio.echo_guard.active",
                "Listening is briefly paused to avoid hearing the pet's own voice",
            )
        self.broker.require(
            Capability.MICROPHONE_CAPTURE,
            explicit_user_action=explicit_user_action,
        )
        self.capture.start()
        self._set_state(AudioState.LISTENING)

    def finish_listening(self) -> VoiceTurn:
        if self.state is not AudioState.LISTENING:
            raise RuntimeError("Audio session is not listening")
        started = time.monotonic()
        wave_bytes = self.capture.stop()
        self._set_state(AudioState.TRANSCRIBING)
        parts: list[str] = []
        try:
            for partial in self.stt.transcribe(wave_bytes):
                value = " ".join(str(partial).split())
                if not value:
                    continue
                parts.append(value)
                self.partial_text(" ".join(parts))
            transcript = " ".join(parts).strip()
            if not transcript:
                raise PetError(
                    ErrorCategory.PLATFORM_UNAVAILABLE,
                    "stt.empty",
                    "No speech could be transcribed",
                )
            self._set_state(AudioState.THINKING)
            return VoiceTurn(transcript, self.stt.name, len(wave_bytes), time.monotonic() - started)
        except Exception:
            self._set_state(AudioState.ERROR)
            raise

    def capture_for_transcription(self) -> bytes:
        if self.state is not AudioState.LISTENING:
            raise RuntimeError("Audio session is not listening")
        wave_bytes = self.capture.stop()
        self._set_state(AudioState.TRANSCRIBING)
        return wave_bytes

    def complete_transcription(self, transcript: str, *, provider: str, audio_bytes: int) -> VoiceTurn:
        if self.state is not AudioState.TRANSCRIBING:
            raise RuntimeError("Audio session is not transcribing")
        value = " ".join(transcript.strip().split())[:500]
        if not value:
            self._set_state(AudioState.ERROR)
            raise ValueError("No speech was recognized")
        self.partial_text(value)
        self._set_state(AudioState.THINKING)
        return VoiceTurn(value, provider, max(0, int(audio_bytes)), 0.0)

    def speak(self, text: str) -> None:
        value = " ".join(text.strip().split())
        if not value:
            return
        if self.state is AudioState.LISTENING:
            self.capture.cancel()
        self._set_state(AudioState.SPEAKING)
        self.tts.speak(value)

    def speech_finished(self) -> None:
        self._last_speech_stopped = time.monotonic()
        self._set_state(AudioState.IDLE)

    def interrupt(self) -> None:
        if self.state is AudioState.LISTENING:
            self.capture.cancel()
        if self.state is AudioState.SPEAKING:
            self.tts.stop()
            self._last_speech_stopped = time.monotonic()
        self._set_state(AudioState.INTERRUPTED)

    def reset(self) -> None:
        self._set_state(AudioState.IDLE)

    def _set_state(self, state: AudioState) -> None:
        self.state = state
        self.state_changed(state)


class ArecordCapture:
    """Ephemeral Linux PCM capture; the temporary WAV is deleted on stop/cancel."""

    def __init__(self, *, executable: str | None = None, max_seconds: int = 30) -> None:
        self.executable = executable or shutil.which("arecord") or ""
        self.max_seconds = max(1, min(120, int(max_seconds)))
        self._process: subprocess.Popen[bytes] | None = None
        self._path: Path | None = None

    @property
    def available(self) -> bool:
        return bool(self.executable and Path(self.executable).is_file())

    def start(self) -> None:
        if not self.available:
            raise PetError(
                ErrorCategory.PLATFORM_UNAVAILABLE,
                "audio.capture.unavailable",
                "The arecord audio capture command is unavailable",
            )
        if self._process is not None:
            raise RuntimeError("Audio capture is already active")
        descriptor, name = tempfile.mkstemp(prefix="vla-pet-voice-", suffix=".wav")
        os.close(descriptor)
        self._path = Path(name)
        self._path.chmod(0o600)
        self._process = subprocess.Popen(
            [
                self.executable,
                "-q",
                "-t",
                "wav",
                "-f",
                "S16_LE",
                "-r",
                "16000",
                "-c",
                "1",
                "-d",
                str(self.max_seconds),
                str(self._path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    def stop(self) -> bytes:
        process, path = self._process, self._path
        self._process = None
        self._path = None
        if process is None or path is None:
            raise RuntimeError("Audio capture is not active")
        try:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
            _stdout, stderr = process.communicate(timeout=2.0)
            if process.returncode not in {0, -signal.SIGINT} and not path.exists():
                raise RuntimeError(stderr.decode("utf-8", "replace")[:500])
            return path.read_bytes()
        finally:
            path.unlink(missing_ok=True)

    def cancel(self) -> None:
        process, path = self._process, self._path
        self._process = None
        self._path = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=0.5)
        if path is not None:
            path.unlink(missing_ok=True)


class CommandSTTProvider:
    """Configured argv-only STT bridge; no shell expansion is performed."""

    name = "command-stt"

    def __init__(self, command: tuple[str, ...], *, timeout_s: float = 120.0) -> None:
        if not command or not Path(command[0]).is_file():
            raise ValueError("STT command executable must be an existing absolute path")
        self.command = command
        self.timeout_s = max(1.0, min(600.0, float(timeout_s)))

    def transcribe(self, wave_bytes: bytes) -> Iterable[str]:
        descriptor, name = tempfile.mkstemp(prefix="vla-pet-stt-", suffix=".wav")
        path = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(wave_bytes)
            path.chmod(0o600)
            command = [argument.replace("{audio}", str(path)) for argument in self.command]
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
            transcript = " ".join(result.stdout.split())
            if transcript:
                yield transcript
        finally:
            path.unlink(missing_ok=True)


class MockAudioCapture:
    def __init__(self, payload: bytes = b"RIFFmock") -> None:
        self.payload = payload
        self.active = False

    def start(self) -> None:
        self.active = True

    def stop(self) -> bytes:
        if not self.active:
            raise RuntimeError("not active")
        self.active = False
        return self.payload

    def cancel(self) -> None:
        self.active = False


class MockSTTProvider:
    name = "mock-stt"

    def __init__(self, partials: tuple[str, ...] = ("hello", "pet")) -> None:
        self.partials = partials

    def transcribe(self, _wave_bytes: bytes) -> Iterable[str]:
        yield from self.partials


class UnavailableSTTProvider:
    name = "unavailable-stt"

    def transcribe(self, _wave_bytes: bytes) -> Iterable[str]:
        raise PetError(
            ErrorCategory.PLATFORM_UNAVAILABLE,
            "stt.provider.unavailable",
            "No local STT command is configured; text chat is still available",
        )


class MockTTSProvider:
    name = "mock-tts"

    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.stopped = False

    def speak(self, text: str) -> None:
        self.spoken.append(text)

    def stop(self) -> None:
        self.stopped = True
