from __future__ import annotations

import time

import pytest

from vla_pet.errors import PetError
from vla_pet.permissions import Capability, PermissionBroker
from vla_pet.voice import (
    AudioSession,
    AudioState,
    MockAudioCapture,
    MockSTTProvider,
    MockTTSProvider,
)


def test_push_to_talk_partial_transcript_speech_and_interrupt() -> None:
    states: list[AudioState] = []
    partials: list[str] = []
    capture = MockAudioCapture()
    tts = MockTTSProvider()
    session = AudioSession(
        capture,
        MockSTTProvider(("hello", "Momo")),
        tts,
        PermissionBroker({Capability.MICROPHONE_CAPTURE}),
        echo_guard_s=0,
        state_changed=states.append,
        partial_text=partials.append,
    )
    session.begin_listening()
    turn = session.finish_listening()
    assert turn.transcript == "hello Momo" and partials == ["hello", "hello Momo"]
    assert states[:3] == [AudioState.LISTENING, AudioState.TRANSCRIBING, AudioState.THINKING]
    session.speak("Hi there")
    assert tts.spoken == ["Hi there"] and session.state is AudioState.SPEAKING
    started = time.perf_counter()
    session.interrupt()
    assert time.perf_counter() - started < 0.1
    assert tts.stopped and session.state is AudioState.INTERRUPTED


def test_microphone_denial_starts_zero_capture_work() -> None:
    capture = MockAudioCapture()
    session = AudioSession(
        capture,
        MockSTTProvider(),
        MockTTSProvider(),
        PermissionBroker(),
    )
    with pytest.raises(PetError):
        session.begin_listening()
    assert not capture.active and session.state is AudioState.IDLE


def test_audio_self_echo_guard_rejects_immediate_relisten() -> None:
    session = AudioSession(
        MockAudioCapture(),
        MockSTTProvider(),
        MockTTSProvider(),
        PermissionBroker({Capability.MICROPHONE_CAPTURE}),
        echo_guard_s=10,
    )
    session.speak("hello")
    session.speech_finished()
    with pytest.raises(PetError):
        session.begin_listening()
