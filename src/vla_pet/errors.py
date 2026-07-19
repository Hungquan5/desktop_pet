from __future__ import annotations

from enum import Enum


class ErrorCategory(str, Enum):
    CONFIGURATION = "configuration"
    PERMISSION_DENIED = "permission_denied"
    PLATFORM_UNAVAILABLE = "platform_unavailable"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_INFERENCE = "model_inference"
    INVALID_MODEL_OUTPUT = "invalid_model_output"
    PERSISTENCE = "persistence"
    CHARACTER_PACK = "character_pack"
    WORKER_TIMEOUT = "worker_timeout"
    INTERNAL = "internal"


class PetError(RuntimeError):
    def __init__(self, category: ErrorCategory, code: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.code = code

    def diagnostic(self) -> dict[str, str]:
        return {"category": self.category.value, "code": self.code, "message": str(self)}


def error_diagnostic(exc: Exception, operation: str) -> dict[str, str]:
    if isinstance(exc, PetError):
        return exc.diagnostic()
    if isinstance(exc, (ImportError, ModuleNotFoundError, FileNotFoundError)):
        category = ErrorCategory.MODEL_UNAVAILABLE
    elif operation in {"chat", "narrate", "notify", "ask_screen", "decide"}:
        category = ErrorCategory.MODEL_INFERENCE
    else:
        category = ErrorCategory.INTERNAL
    return {
        "category": category.value,
        "code": f"{operation}.failed",
        "message": f"{type(exc).__name__}: {exc}",
    }
