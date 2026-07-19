from __future__ import annotations

import re

from vla_pet.contracts import ActionEvent


def template_narration(event: ActionEvent) -> str:
    """CPU-free fallback used only when VLM generation is unavailable."""
    phrases = {
        "walk": "I went for a tiny walk!",
        "jump": "I jumped as high as I could!",
        "throw": "I tossed my little toy!",
        "happy": "I feel wonderfully happy!",
        "sad": "I feel a little gloomy.",
        "idle": "I paused to look around.",
    }
    if "could not" in event.result:
        return "I tried, but it was out of reach."
    return phrases[event.executed.value]


def sanitize_narration(text: str, *, max_words: int = 12, max_chars: int = 80) -> str:
    cleaned = " ".join(text.replace("\x00", " ").strip().strip('"\'').split())
    if not cleaned:
        return ""
    first_sentence = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0]
    words = first_sentence.split()[:max_words]
    result = " ".join(words)[:max_chars].rstrip()
    if result and result[-1] not in ".!?":
        result += "."
    return result
