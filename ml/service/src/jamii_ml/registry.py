"""Reads ml/registry.yaml and loads the active model for each task."""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

TASKS = ("classifier", "transcriber", "ner")


@dataclass
class ModelSpec:
    task: str
    version: str
    kind: str
    path: Path | None = None
    options: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)


def registry_path() -> Path:
    return Path(os.environ.get("JAMII_ML_REGISTRY", Path(__file__).resolve().parents[3] / "registry.yaml"))


def load(path: Path | None = None) -> dict:
    path = path or registry_path()
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    for task in TASKS:
        data.setdefault(task, {"active": None, "versions": {}})
        data[task].setdefault("versions", {})
        data[task]["versions"] = data[task]["versions"] or {}
    return data


def save(data: dict, path: Path | None = None) -> None:
    path = path or registry_path()
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def active_spec(task: str, path: Path | None = None) -> ModelSpec | None:
    path = path or registry_path()
    data = load(path)
    version = data[task].get("active")
    if not version:
        return None
    entry = dict(data[task]["versions"].get(version) or {})
    if not entry:
        raise ValueError(f"registry: {task}.active = {version!r} but that version is not listed")
    model_path = entry.pop("path", None)
    if model_path:
        model_path = Path(model_path)
        if not model_path.is_absolute():
            model_path = path.parent / model_path
    return ModelSpec(
        task=task,
        version=version,
        kind=entry.pop("kind"),
        path=model_path,
        metrics=entry.pop("metrics", {}) or {},
        options=entry,
    )
