from __future__ import annotations

import json

import pytest

from vla_pet.cli import main
from vla_pet.contracts import ChatRequest
from vla_pet.openai_compatible import OpenAICompatibleLanguage


def test_compatible_provider_restricts_plain_http_to_localhost() -> None:
    with pytest.raises(ValueError):
        OpenAICompatibleLanguage(
            "http://example.com:8000", "model", persona_prompt="Be concise"
        )
    provider = OpenAICompatibleLanguage(
        "http://127.0.0.1:11434", "model", persona_prompt="Be concise"
    )
    assert provider.endpoint.endswith("11434")


def test_compatible_provider_chat_contract(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit: int) -> bytes:
            return json.dumps(
                {"choices": [{"message": {"content": "I'll jump now!"}}]}
            ).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    provider = OpenAICompatibleLanguage(
        "http://localhost:11434", "tiny", persona_prompt="Be concise"
    )
    result = provider.chat(ChatRequest("Can you jump?", memory_context="User likes concise replies"))
    assert result.reply == "I'll jump now!" and result.requested_action is not None


def test_cli_rejects_incomplete_or_insecure_remote_provider() -> None:
    with pytest.raises(SystemExit):
        main(["--language-provider", "openai-compatible", "--headless"])
    with pytest.raises(SystemExit):
        main(
            [
                "--language-provider",
                "openai-compatible",
                "--language-endpoint",
                "http://example.com:8000",
                "--headless",
            ]
        )
