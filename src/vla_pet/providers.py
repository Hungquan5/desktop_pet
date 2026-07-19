from __future__ import annotations

from typing import Protocol

from vla_pet.contracts import (
    AudioTranscription,
    ChatRequest,
    ChatResult,
    LanguageNarration,
    NotificationRequest,
    PetAction,
    SandboxObservation,
    VisualQuestion,
)


class ActionProvider(Protocol):
    def decide(self, observation: SandboxObservation) -> PetAction: ...


class LanguageProvider(Protocol):
    def chat(self, request: ChatRequest) -> ChatResult: ...

    def narrate(self, request: LanguageNarration) -> str: ...

    def react_notification(self, request: NotificationRequest) -> str: ...

    def answer_from_visual(self, request: VisualQuestion, visual_evidence: str) -> str: ...


class VisionProvider(ActionProvider, Protocol):
    def answer(self, request: VisualQuestion) -> str: ...


class SpeechRecognitionProvider(Protocol):
    name: str

    def transcribe(self, request: AudioTranscription) -> str: ...


class LocalProviderRegistry:
    """Lazy provider owner used only inside the spawned AI process."""

    def __init__(self, config: object) -> None:
        self.config = config
        self._visual: ActionProvider | None = None
        self._language: LanguageProvider | None = None
        self._stt: SpeechRecognitionProvider | None = None
        self._visual_error: str = ""
        self._language_error: str = ""
        self._stt_error: str = ""

    def visual(self) -> ActionProvider:
        if self._visual_error:
            raise RuntimeError(self._visual_error)
        if self._visual is not None:
            return self._visual
        try:
            if self.config.policy_backend == "vlm":
                from vla_pet.policy import SmolVLMPetPolicy

                self._visual = SmolVLMPetPolicy(
                    self.config.model_id,
                    self.config.device,
                    getattr(self.config, "quantization", "auto"),
                )
            else:
                from vla_pet.policy import SmolVLAPetPolicy

                self._visual = SmolVLAPetPolicy(
                    self.config.model_id,
                    self.config.device,
                    self.config.action_mode,
                )
            return self._visual
        except Exception as exc:
            self._visual_error = f"{type(exc).__name__}: {exc}"
            raise

    def speech_recognition(self) -> SpeechRecognitionProvider:
        if self._stt_error:
            raise RuntimeError(self._stt_error)
        if self._stt is not None:
            return self._stt
        try:
            from vla_pet.speech_recognition import LocalWhisperSTT

            self._stt = LocalWhisperSTT(
                getattr(self.config, "stt_model_id", "openai/whisper-tiny"),
                self.config.device,
            )
            return self._stt
        except Exception as exc:
            self._stt_error = f"{type(exc).__name__}: {exc}"
            raise

    def vision(self) -> VisionProvider:
        provider = self.visual()
        if not hasattr(provider, "answer"):
            raise RuntimeError("The configured action provider has no vision-question capability")
        return provider  # type: ignore[return-value]

    def language(self) -> LanguageProvider:
        if self._language_error:
            raise RuntimeError(self._language_error)
        if self._language is not None:
            return self._language
        try:
            if getattr(self.config, "language_provider", "transformers") == "transformers":
                from vla_pet.policy import SmolLMPetLanguage

                self._language = SmolLMPetLanguage(
                    self.config.language_model_id,
                    self.config.device,
                    getattr(self.config, "language_quantization", "none"),
                    persona_name=getattr(self.config, "persona_name", "Momo"),
                    persona_prompt=getattr(self.config, "persona_prompt", ""),
                )
            else:
                from vla_pet.openai_compatible import OpenAICompatibleLanguage

                self._language = OpenAICompatibleLanguage(
                    self.config.language_endpoint,
                    self.config.language_model_id,
                    persona_prompt=getattr(self.config, "persona_prompt", ""),
                    api_key_env=getattr(self.config, "language_api_key_env", ""),
                    timeout_s=getattr(self.config, "timeout_s", 120.0),
                )
            return self._language
        except Exception as exc:
            self._language_error = f"{type(exc).__name__}: {exc}"
            raise
