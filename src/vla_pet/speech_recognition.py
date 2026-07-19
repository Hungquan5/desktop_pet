from __future__ import annotations

import io
import wave

import numpy as np

from vla_pet.contracts import AudioTranscription


class LocalWhisperSTT:
    """Lazy Transformers Whisper provider owned by the existing AI worker."""

    def __init__(self, model_id: str, device: str = "cpu") -> None:
        try:
            import torch
            from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor
        except ImportError as exc:  # pragma: no cover - live optional path
            raise RuntimeError("Whisper support requires the models optional dependencies") from exc
        self.name = model_id
        self._torch = torch
        self._device = torch.device(device)
        self._processor = AutoProcessor.from_pretrained(model_id)
        self._model = AutoModelForSpeechSeq2Seq.from_pretrained(model_id).to(self._device).eval()

    def transcribe(self, request: AudioTranscription) -> str:
        request.validate()
        samples, rate = self._decode_wave(request.wave_bytes)
        inputs = self._processor(
            samples,
            sampling_rate=rate,
            return_tensors="pt",
            return_attention_mask=True,
        )
        features = inputs.input_features.to(self._device)
        generation: dict[str, object] = {"max_new_tokens": 96, "task": "transcribe"}
        if getattr(inputs, "attention_mask", None) is not None:
            generation["attention_mask"] = inputs.attention_mask.to(self._device)
        if request.language:
            generation["language"] = request.language
        with self._torch.inference_mode():
            generated = self._model.generate(features, **generation)
        text = self._processor.batch_decode(generated, skip_special_tokens=True)[0]
        return " ".join(text.split())[:500]

    @staticmethod
    def _decode_wave(payload: bytes) -> tuple[np.ndarray, int]:
        with wave.open(io.BytesIO(payload), "rb") as source:
            channels = source.getnchannels()
            width = source.getsampwidth()
            rate = source.getframerate()
            frames = source.readframes(source.getnframes())
        if channels != 1 or width != 2 or rate != 16_000:
            raise ValueError("STT expects mono 16-bit 16 kHz WAV audio")
        samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
        return samples, rate
