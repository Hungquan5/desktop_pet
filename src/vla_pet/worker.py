from __future__ import annotations

import multiprocessing as mp
import os
import queue
import signal
import time
from dataclasses import dataclass
from typing import Any

from vla_pet.contracts import AudioTranscription, ChatResult, WorkerRequest, WorkerResponse
from vla_pet.errors import error_diagnostic


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    mock_policy: bool = False
    model_id: str = "HuggingFaceTB/SmolVLM2-256M-Video-Instruct"
    language_model_id: str = "HuggingFaceTB/SmolLM2-360M-Instruct"
    device: str = "cpu"
    timeout_s: float = 180.0
    offline: bool = False
    action_mode: str = "sandbox"
    policy_backend: str = "vlm"
    quantization: str = "auto"
    language_quantization: str = "none"
    persona_name: str = "Momo"
    persona_prompt: str = (
        "You are Momo, a warm and playful tiny desktop pet. Answer directly and concisely."
    )
    stt_model_id: str = "openai/whisper-tiny"
    language_provider: str = "transformers"
    language_endpoint: str = ""
    language_api_key_env: str = ""


class MockRequestHandler:
    """Shared deterministic request handler for tests, mock mode, and safe mode."""

    def __init__(self, config: WorkerConfig) -> None:
        from vla_pet.policy import MockPetPolicy

        self._policy = MockPetPolicy(config.action_mode)

    def handle(self, request: WorkerRequest, started: float | None = None) -> WorkerResponse:
        started = time.monotonic() if started is None else started
        request.payload.validate()
        if request.kind == "chat":
            from vla_pet.policy import infer_habitat_intent

            habitat_intent = infer_habitat_intent(request.payload.message)
            payload: object = ChatResult(
                "Okay—let's do that!" if habitat_intent else "Hi! I'm happy to chat with you.",
                habitat_intent=habitat_intent,
            )
        elif request.kind == "transcribe":
            payload = "hello from voice"
        elif request.kind == "notify":
            payload = "A new notification arrived."
        elif request.kind == "narrate":
            from vla_pet.narration import template_narration

            payload = template_narration(request.payload.event)
        elif request.kind == "ask_screen":
            context = request.payload.notification_context
            payload = (
                f"The latest notification says: {context[:160]}"
                if context
                else "I received the screen question."
            )
        elif request.kind == "decide":
            payload = self._policy.decide(request.payload)
        elif request.kind == "habitat":
            environment = request.payload.environment
            payload = environment.candidates[0]
        else:
            raise ValueError(f"Unsupported mock request kind: {request.kind}")
        metadata: dict[str, Any] = {}
        if request.kind in {"decide", "habitat"}:
            metadata = {
                "sequence_id": request.payload.sequence_id,
                "requested_action": (
                    request.payload.requested_action.value
                    if request.kind == "decide" and request.payload.requested_action is not None
                    else ""
                ),
            }
        elif request.kind == "transcribe":
            metadata = {"audio_bytes": len(request.payload.wave_bytes)}
        return WorkerResponse(
            request.request_id,
            request.kind,
            True,
            payload,
            "mock",
            time.monotonic() - started,
            metadata=metadata,
        )


class InlineMockWorkerClient:
    """Worker-shaped client that avoids a process when no model is enabled."""

    def __init__(self, config: WorkerConfig) -> None:
        self.config = config
        self._handler = MockRequestHandler(config)
        self._next_id = 1
        self._pending: dict[int, str] = {}
        self._responses: list[WorkerResponse] = []
        self._cancelled: set[int] = set()

    def start(self) -> None:
        pass

    def submit(self, kind: str, payload: Any) -> int:
        request_id = self._next_id
        self._next_id += 1
        request = WorkerRequest(request_id, kind, payload)
        self._pending[request_id] = kind
        self._responses.append(self._handler.handle(request))
        return request_id

    def poll(self) -> list[WorkerResponse]:
        responses, self._responses = self._responses, []
        responses = [response for response in responses if response.request_id not in self._cancelled]
        for response in responses:
            self._pending.pop(response.request_id, None)
        self._cancelled.clear()
        return responses

    def cancel(self, kind: str) -> int:
        identifiers = [identifier for identifier, pending in self._pending.items() if pending == kind]
        self._cancelled.update(identifiers)
        for identifier in identifiers:
            self._pending.pop(identifier, None)
        return len(identifiers)

    def timed_out(self) -> bool:
        return False

    def stop(self) -> None:
        self._pending.clear()
        self._responses.clear()
        self._cancelled.clear()

    @property
    def pending_kinds(self) -> tuple[str, ...]:
        return tuple(self._pending.values())

    @property
    def process_id(self) -> int | None:
        return None


def _worker_main(requests: Any, responses: Any, config: WorkerConfig) -> None:
    # The UI process owns terminal signal handling and sends an orderly queue
    # shutdown. Ignoring SIGINT here prevents duplicate Ctrl+C tracebacks.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if config.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    if not config.mock_policy:
        try:
            import torch

            torch.set_num_threads(max(1, min(6, (os.cpu_count() or 2) - 1)))
        except ImportError:
            pass

    from vla_pet.providers import LocalProviderRegistry

    providers = LocalProviderRegistry(config)
    mock_handler = MockRequestHandler(config) if config.mock_policy else None

    while True:
        request: WorkerRequest = requests.get()
        if request.kind == "shutdown":
            return
        started = time.monotonic()

        if request.kind in (
            "decide",
            "habitat",
            "ask_screen",
            "chat",
            "narrate",
            "notify",
            "transcribe",
        ):
            try:
                if mock_handler is not None:
                    responses.put(mock_handler.handle(request, started))
                    continue
                if request.kind == "chat":
                    request.payload.validate()
                    result = providers.language().chat(request.payload)
                    responses.put(
                        WorkerResponse(
                            request.request_id,
                            "chat",
                            True,
                            result,
                            config.language_model_id,
                            time.monotonic() - started,
                        )
                    )
                    continue

                if request.kind == "transcribe":
                    if not isinstance(request.payload, AudioTranscription):
                        raise ValueError("Invalid audio transcription payload")
                    request.payload.validate()
                    text = providers.speech_recognition().transcribe(request.payload)
                    if not text:
                        raise ValueError("No speech was recognized")
                    responses.put(
                        WorkerResponse(
                            request.request_id,
                            "transcribe",
                            True,
                            text,
                            config.stt_model_id,
                            time.monotonic() - started,
                            metadata={"audio_bytes": len(request.payload.wave_bytes)},
                        )
                    )
                    continue

                if request.kind == "notify":
                    request.payload.validate()
                    text = providers.language().react_notification(request.payload)
                    responses.put(
                        WorkerResponse(
                            request.request_id,
                            "notify",
                            True,
                            text,
                            config.language_model_id,
                            time.monotonic() - started,
                        )
                    )
                    continue
                if request.kind == "narrate":
                    request.payload.validate()
                    text = providers.language().narrate(request.payload)
                    responses.put(
                        WorkerResponse(
                            request.request_id,
                            "narrate",
                            True,
                            text,
                            config.language_model_id,
                            time.monotonic() - started,
                        )
                    )
                    continue
                if request.kind == "ask_screen":
                    request.payload.validate()
                    if config.policy_backend != "vlm":
                        raise RuntimeError("Screen questions require --policy vlm")
                    evidence = providers.vision().answer(request.payload)
                    answer = providers.language().answer_from_visual(request.payload, evidence)
                    responses.put(
                        WorkerResponse(
                            request.request_id,
                            "ask_screen",
                            True,
                            answer,
                            f"{config.model_id} + {config.language_model_id}",
                            time.monotonic() - started,
                        )
                    )
                    continue

                if request.kind == "habitat":
                    request.payload.validate()
                    intent = providers.visual().choose_habitat(request.payload)
                    responses.put(
                        WorkerResponse(
                            request.request_id,
                            "habitat",
                            True,
                            intent,
                            config.model_id,
                            time.monotonic() - started,
                            metadata={"sequence_id": request.payload.sequence_id},
                        )
                    )
                    continue

                action = providers.visual().decide(request.payload)
                responses.put(
                    # Preserve the language-layer intent so the overlay can
                    # retry it if mouse input makes this visual decision stale.
                    WorkerResponse(
                        request.request_id,
                        "decide",
                        True,
                        action,
                        config.model_id,
                        time.monotonic() - started,
                        metadata={
                            "sequence_id": request.payload.sequence_id,
                            "requested_action": (
                                request.payload.requested_action.value
                                if request.payload.requested_action is not None
                                else ""
                            ),
                        },
                    )
                )
            except Exception as exc:  # worker boundary must not crash the UI
                error = f"{type(exc).__name__}: {exc}"
                diagnostic = error_diagnostic(exc, request.kind)
                if request.kind == "ask_screen":
                    responses.put(
                        WorkerResponse(
                            request.request_id,
                            "ask_screen",
                            False,
                            "I couldn't inspect the screen just now.",
                            "fallback",
                            time.monotonic() - started,
                            error,
                            metadata=diagnostic,
                        )
                    )
                    continue
                if request.kind == "chat":
                    responses.put(
                        WorkerResponse(
                            request.request_id,
                            "chat",
                            False,
                            ChatResult("I'm having trouble thinking right now, but I'm still here!"),
                            "fallback",
                            time.monotonic() - started,
                            error,
                            metadata=diagnostic,
                        )
                    )
                    continue
                if request.kind == "narrate":
                    from vla_pet.narration import template_narration

                    event = getattr(request.payload, "event", request.payload)
                    responses.put(
                        WorkerResponse(
                            request.request_id,
                            "narrate",
                            False,
                            template_narration(event),
                            "template-fallback",
                            time.monotonic() - started,
                            error,
                            metadata=diagnostic,
                        )
                    )
                    continue
                if request.kind == "notify":
                    responses.put(
                        WorkerResponse(
                            request.request_id,
                            "notify",
                            False,
                            "A notification arrived, but I couldn't summarize it safely.",
                            "fallback",
                            time.monotonic() - started,
                            error,
                            metadata=diagnostic,
                        )
                    )
                    continue
                if request.kind == "transcribe":
                    responses.put(
                        WorkerResponse(
                            request.request_id,
                            "transcribe",
                            False,
                            "",
                            "fallback",
                            time.monotonic() - started,
                            error,
                            metadata=diagnostic,
                        )
                    )
                    continue
                if request.kind == "habitat":
                    from vla_pet.contracts import HabitatIntent

                    responses.put(
                        WorkerResponse(
                            request.request_id,
                            "habitat",
                            False,
                            HabitatIntent.RETURN_HOME,
                            "fallback",
                            time.monotonic() - started,
                            error,
                            metadata={
                                "sequence_id": getattr(request.payload, "sequence_id", -1),
                                **diagnostic,
                            },
                        )
                    )
                    continue
                from vla_pet.contracts import ActionKind, PetAction

                fallback = PetAction(
                    ActionKind.IDLE,
                    duration=0.8,
                    source="fallback",
                    note=error,
                )
                responses.put(
                    WorkerResponse(
                        request.request_id,
                        "decide",
                        False,
                        fallback,
                        "fallback",
                        time.monotonic() - started,
                        error,
                        metadata={
                            "sequence_id": request.payload.sequence_id,
                            "requested_action": (
                                request.payload.requested_action.value
                                if request.payload.requested_action is not None
                                else ""
                            ),
                            **diagnostic,
                        },
                    )
                )


class AIWorkerClient:
    def __init__(self, config: WorkerConfig) -> None:
        self.config = config
        self._context = mp.get_context("spawn")
        self._requests = self._context.Queue()
        self._responses = self._context.Queue()
        self._process: mp.Process | None = None
        self._next_id = 1
        self._pending: dict[int, tuple[str, float]] = {}
        self._cancelled: set[int] = set()

    def start(self) -> None:
        if self._process and self._process.is_alive():
            return
        self._process = self._context.Process(
            target=_worker_main,
            args=(self._requests, self._responses, self.config),
            name="vla-pet-ai",
            daemon=True,
        )
        self._process.start()

    def submit(self, kind: str, payload: Any) -> int:
        request_id = self._next_id
        self._next_id += 1
        self._pending[request_id] = (kind, time.monotonic())
        self._requests.put(WorkerRequest(request_id, kind, payload))
        return request_id

    def poll(self) -> list[WorkerResponse]:
        results: list[WorkerResponse] = []
        while True:
            try:
                response = self._responses.get_nowait()
            except queue.Empty:
                break
            self._pending.pop(response.request_id, None)
            if response.request_id not in self._cancelled:
                results.append(response)
            self._cancelled.discard(response.request_id)
        return results

    def cancel(self, kind: str) -> int:
        identifiers = [
            identifier for identifier, (pending_kind, _started) in self._pending.items()
            if pending_kind == kind
        ]
        self._cancelled.update(identifiers)
        for identifier in identifiers:
            self._pending.pop(identifier, None)
        return len(identifiers)

    def timed_out(self) -> bool:
        now = time.monotonic()
        return any(now - started > self.config.timeout_s for _, started in self._pending.values())

    def stop(self) -> None:
        if not self._process:
            return
        if self._process.is_alive():
            self._requests.put(WorkerRequest(0, "shutdown", None))
            self._process.join(timeout=2.0)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=1.0)
        self._process = None
        self._cancelled.clear()

    @property
    def pending_kinds(self) -> tuple[str, ...]:
        return tuple(kind for kind, _ in self._pending.values())

    @property
    def process_id(self) -> int | None:
        return self._process.pid if self._process and self._process.is_alive() else None
