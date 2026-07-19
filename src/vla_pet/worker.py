from __future__ import annotations

import multiprocessing as mp
import os
import queue
import time
from dataclasses import dataclass
from typing import Any

from vla_pet.contracts import ChatResult, WorkerRequest, WorkerResponse


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


def _worker_main(requests: Any, responses: Any, config: WorkerConfig) -> None:
    if config.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    try:
        import torch

        torch.set_num_threads(max(1, min(6, (os.cpu_count() or 2) - 1)))
    except ImportError:
        pass

    visual_policy = None
    language_policy = None
    visual_error = ""
    language_error = ""

    def get_visual_policy():
        nonlocal visual_policy, visual_error
        if visual_error:
            raise RuntimeError(visual_error)
        if visual_policy is not None:
            return visual_policy
        try:
            if config.policy_backend == "vlm":
                from vla_pet.policy import SmolVLMPetPolicy

                visual_policy = SmolVLMPetPolicy(
                    config.model_id,
                    config.device,
                    getattr(config, "quantization", "auto"),
                )
            else:
                from vla_pet.policy import SmolVLAPetPolicy

                visual_policy = SmolVLAPetPolicy(config.model_id, config.device, config.action_mode)
            return visual_policy
        except Exception as exc:
            visual_error = f"{type(exc).__name__}: {exc}"
            raise

    def get_language_policy():
        nonlocal language_policy, language_error
        if language_error:
            raise RuntimeError(language_error)
        if language_policy is not None:
            return language_policy
        try:
            from vla_pet.policy import SmolLMPetLanguage

            language_policy = SmolLMPetLanguage(
                getattr(config, "language_model_id", "HuggingFaceTB/SmolLM2-360M-Instruct"),
                config.device,
                getattr(config, "language_quantization", "none"),
            )
            return language_policy
        except Exception as exc:
            language_error = f"{type(exc).__name__}: {exc}"
            raise

    while True:
        request: WorkerRequest = requests.get()
        if request.kind == "shutdown":
            return
        started = time.monotonic()

        if request.kind in ("decide", "ask_screen", "chat", "narrate"):
            try:
                if request.kind == "chat":
                    if config.mock_policy:
                        result = ChatResult("Hi! I'm happy to chat with you.")
                    else:
                        result = get_language_policy().chat(request.payload)
                    responses.put(
                        WorkerResponse(
                            request.request_id,
                            "chat",
                            True,
                            result,
                            "mock"
                            if config.mock_policy
                            else getattr(config, "language_model_id", "HuggingFaceTB/SmolLM2-360M-Instruct"),
                            time.monotonic() - started,
                        )
                    )
                    continue

                if request.kind == "narrate":
                    event = getattr(request.payload, "event", request.payload)
                    if config.mock_policy:
                        from vla_pet.narration import template_narration

                        text = template_narration(event)
                    else:
                        text = get_language_policy().narrate(request.payload)
                    responses.put(
                        WorkerResponse(
                            request.request_id,
                            "narrate",
                            True,
                            text,
                            "mock"
                            if config.mock_policy
                            else getattr(config, "language_model_id", "HuggingFaceTB/SmolLM2-360M-Instruct"),
                            time.monotonic() - started,
                        )
                    )
                    continue

                if request.kind == "ask_screen":
                    if config.mock_policy:
                        context = request.payload.notification_context
                        answer = "I received the screen question."
                        if context:
                            answer = f"The latest notification says: {context[:160]}"
                    elif config.policy_backend != "vlm":
                        raise RuntimeError("Screen questions require --policy vlm")
                    else:
                        evidence = get_visual_policy().answer(request.payload)
                        answer = get_language_policy().answer_from_visual(request.payload, evidence)
                    responses.put(
                        WorkerResponse(
                            request.request_id,
                            "ask_screen",
                            True,
                            answer,
                            (
                                "mock"
                                if config.mock_policy
                                else (
                                    f"{config.model_id} + "
                                    f"{getattr(config, 'language_model_id', 'HuggingFaceTB/SmolLM2-360M-Instruct')}"
                                )
                            ),
                            time.monotonic() - started,
                        )
                    )
                    continue

                if config.mock_policy:
                    from vla_pet.policy import MockPetPolicy

                    if visual_policy is None:
                        visual_policy = MockPetPolicy(config.action_mode)
                    action = visual_policy.decide(request.payload)
                else:
                    action = get_visual_policy().decide(request.payload)
                responses.put(
                    # Preserve the language-layer intent so the overlay can
                    # retry it if mouse input makes this visual decision stale.
                    WorkerResponse(
                        request.request_id,
                        "decide",
                        True,
                        action,
                        "mock" if config.mock_policy else config.model_id,
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
            results.append(response)
        return results

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

    @property
    def pending_kinds(self) -> tuple[str, ...]:
        return tuple(kind for kind, _ in self._pending.values())

    @property
    def process_id(self) -> int | None:
        return self._process.pid if self._process and self._process.is_alive() else None
