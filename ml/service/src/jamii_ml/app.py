"""The model service API. Internal only: Caddy never routes to it; only workers call it.

It returns 503 for any task without an active model, which the workers treat exactly like
the service being down: the report goes to a person.
"""

import logging
from functools import lru_cache
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from jamii_ml import registry
from jamii_ml.classifiers import Classifier, KeywordClassifier, SklearnClassifier

log = logging.getLogger("jamii.ml")
app = FastAPI(title="Jamii Pulse model service", docs_url="/docs")

MAX_AUDIO = 5_000_000


class ThemeIn(BaseModel):
    code: str
    keywords: list[str] = Field(default_factory=list)


class ClassifyIn(BaseModel):
    text: str = Field(max_length=10_000)
    language: str = "sw"
    themes: list[ThemeIn] = Field(min_length=1)


class ClassifyOut(BaseModel):
    theme: str
    confidence: float
    model_version: str
    scores: dict[str, float]


class RedactIn(BaseModel):
    text: str = Field(max_length=10_000)
    language: str = "sw"


@lru_cache
def classifier() -> Classifier | None:
    spec = registry.active_spec("classifier")
    if spec is None:
        return None
    if spec.kind == "keyword":
        return KeywordClassifier(spec.version)
    if spec.kind == "sklearn":
        return SklearnClassifier(spec.path, spec.version)
    raise ValueError(f"unknown classifier kind {spec.kind}")


@lru_cache
def transcriber():
    spec = registry.active_spec("transcriber")
    if spec is None:
        return None
    from jamii_ml.speech import WhisperTranscriber

    return WhisperTranscriber(spec)


@lru_cache
def ner():
    spec = registry.active_spec("ner")
    if spec is None:
        return None
    from jamii_ml.speech import NerRedactor

    return NerRedactor(spec)


def _unavailable(task: str) -> HTTPException:
    return HTTPException(503, f"no active {task} model")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/v1/models")
def models():
    data = registry.load()
    return {task: data[task].get("active") for task in registry.TASKS}


@app.post("/v1/classify", response_model=ClassifyOut)
def classify(body: ClassifyIn):
    model = classifier()
    if model is None:
        raise _unavailable("classifier")
    p = model.predict(body.text, body.language, [t.model_dump() for t in body.themes])
    return ClassifyOut(theme=p.theme, confidence=p.confidence, model_version=model.version, scores=p.scores)


@app.post("/v1/transcribe")
def transcribe(audio: Annotated[UploadFile, File()], language: Annotated[str, Form()] = "sw"):
    model = transcriber()
    if model is None:
        raise _unavailable("transcriber")
    data = audio.file.read(MAX_AUDIO + 1)
    if not data or len(data) > MAX_AUDIO:
        raise HTTPException(413, "audio empty or too large")
    text, confidence = model.transcribe(data, language)
    return {"text": text, "confidence": confidence, "model_version": model.version}


@app.post("/v1/redact")
def redact(body: RedactIn):
    model = ner()
    if model is None:
        raise _unavailable("ner")
    text, n = model.redact(body.text)
    return {"text": text, "entities": n, "model_version": model.version}
