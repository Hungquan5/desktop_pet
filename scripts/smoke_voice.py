from __future__ import annotations

import io
import math
import struct
import time
import wave

from vla_pet.contracts import AudioTranscription
from vla_pet.paths import AppPaths
from vla_pet.speech_recognition import LocalWhisperSTT


def synthetic_wave() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16_000)
        frames = [
            struct.pack("<h", int(1000 * math.sin(2 * math.pi * 220 * index / 16_000)))
            for index in range(16_000)
        ]
        target.writeframes(b"".join(frames))
    return output.getvalue()


def main() -> int:
    import os

    os.environ.setdefault("HF_HOME", str(AppPaths.discover().model_cache))
    started = time.monotonic()
    provider = LocalWhisperSTT("openai/whisper-tiny", "cpu")
    text = provider.transcribe(AudioTranscription(synthetic_wave()))
    print(
        f"provider={provider.name} latency_s={time.monotonic() - started:.2f} "
        f"synthetic_transcript_chars={len(text)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
