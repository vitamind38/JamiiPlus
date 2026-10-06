"""The only way any code reaches a model. Every model sits behind the model service's one API,
so a model can be replaced without touching the app or the workers."""

from dataclasses import dataclass

import httpx

from jamii_api.config import get_settings


class ModelUnavailable(Exception):
    """The model service is down, slow, or has no active model for this task."""


@dataclass
class Transcription:
    text: str
    confidence: float
    model_version: str


@dataclass
class Prediction:
    theme: str
    confidence: float
    model_version: str


@dataclass
class Redaction:
    text: str
    entities: int
    model_version: str


class ModelClient:
    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        s = get_settings()
        self.base_url = (base_url or s.model_service_url).rstrip("/")
        self.timeout = timeout or s.model_service_timeout_s

    def _post(self, path: str, **kw) -> dict:
        try:
            r = httpx.post(self.base_url + path, timeout=self.timeout, **kw)
        except httpx.HTTPError as e:
            raise ModelUnavailable(f"{path}: {e.__class__.__name__}") from e
        if r.status_code != 200:
            raise ModelUnavailable(f"{path}: HTTP {r.status_code}")
        return r.json()

    def redact(self, text: str, language: str) -> Redaction:
        d = self._post("/v1/redact", json={"text": text, "language": language})
        return Redaction(d["text"], int(d.get("entities", 0)), d["model_version"])

    def transcribe(self, audio: bytes, mime: str, language: str) -> Transcription:
        d = self._post("/v1/transcribe", files={"audio": ("note", audio, mime)}, data={"language": language})
        return Transcription(d["text"], float(d["confidence"]), d["model_version"])

    def classify(self, text: str, language: str, themes: list[dict]) -> Prediction:
        d = self._post("/v1/classify", json={"text": text, "language": language, "themes": themes})
        return Prediction(d["theme"], float(d["confidence"]), d["model_version"])
