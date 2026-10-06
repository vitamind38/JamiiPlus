"""Speech-to-text and named-entity redaction. Both load only when a version is active."""

import math
import tempfile
from pathlib import Path

from jamii_ml.registry import ModelSpec


class WhisperTranscriber:
    """A Whisper-family model run with faster-whisper (CTranslate2), on CPU by default."""

    def __init__(self, spec: ModelSpec):
        from faster_whisper import WhisperModel

        self.version = spec.version
        self.model = WhisperModel(
            str(spec.path),
            device=spec.options.get("device", "cpu"),
            compute_type=spec.options.get("compute_type", "int8"),
        )

    def transcribe(self, audio: bytes, language: str) -> tuple[str, float]:
        with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as f:
            f.write(audio)
            tmp = Path(f.name)
        try:
            segments, _ = self.model.transcribe(
                str(tmp), language=language if language in ("sw", "en") else None, vad_filter=True, beam_size=5
            )
            segments = list(segments)
        finally:
            tmp.unlink(missing_ok=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        if not segments:
            return "", 0.0
        # Mean per-token probability, weighted by segment length.
        total = sum(max(s.end - s.start, 0.01) for s in segments)
        conf = sum(math.exp(s.avg_logprob) * max(s.end - s.start, 0.01) for s in segments) / total
        return text, round(conf, 4)


class NerRedactor:
    """Masks person names found by a token-classification model."""

    def __init__(self, spec: ModelSpec):
        from transformers import pipeline

        self.version = spec.version
        self.labels = set(spec.options.get("labels", ["PER"]))
        self.pipe = pipeline("token-classification", model=str(spec.path), aggregation_strategy="simple")

    def redact(self, text: str) -> tuple[str, int]:
        spans = [e for e in self.pipe(text) if e["entity_group"] in self.labels]
        for e in sorted(spans, key=lambda e: e["start"], reverse=True):
            text = text[: e["start"]] + "[NAME]" + text[e["end"] :]
        return text, len(spans)
