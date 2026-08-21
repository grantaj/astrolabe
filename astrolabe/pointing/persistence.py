from __future__ import annotations

import json
from pathlib import Path

from .model import PointingModel


def default_model_path() -> Path:
    """Return the application's default pointing-model persistence path."""
    return Path.home() / ".astrolabe" / "pointing.json"


def save_pointing_model(model: PointingModel, path: Path) -> None:
    """Persist a pointing model atomically to an explicitly selected path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(model.to_dict(), handle, indent=2)
            handle.flush()
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def load_pointing_model(path: Path) -> PointingModel:
    """Load a pointing model from an explicitly selected path."""
    if not path.exists():
        return PointingModel()
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return PointingModel()
    return PointingModel.from_dict(data)
