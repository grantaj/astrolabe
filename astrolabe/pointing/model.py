from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_MODEL_PATH = Path.home() / ".astrolabe" / "pointing.json"


@dataclass
class PointingModel:
    schema_version: int = 1
    b_alpha_rad: float = 0.0
    b_delta_rad: float = 0.0
    num_samples: int = 0
    last_update_utc: datetime.datetime | None = None

    def predict(self) -> tuple[float, float]:
        return self.b_alpha_rad, self.b_delta_rad

    def update(self, d_alpha: float, d_delta: float, *, weight: float = 0.1) -> None:
        weight = max(0.0, min(1.0, weight))
        self.b_alpha_rad = (1.0 - weight) * self.b_alpha_rad + weight * d_alpha
        self.b_delta_rad = (1.0 - weight) * self.b_delta_rad + weight * d_delta
        self.num_samples += 1
        self.last_update_utc = datetime.datetime.now(datetime.timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "b_alpha_rad": self.b_alpha_rad,
            "b_delta_rad": self.b_delta_rad,
            "num_samples": self.num_samples,
            "last_update_utc": self.last_update_utc.isoformat()
            if self.last_update_utc
            else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PointingModel":
        last_update = data.get("last_update_utc")
        parsed_last_update = None
        if isinstance(last_update, str):
            try:
                parsed_last_update = datetime.datetime.fromisoformat(last_update)
            except ValueError:
                parsed_last_update = None
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            b_alpha_rad=float(data.get("b_alpha_rad", 0.0)),
            b_delta_rad=float(data.get("b_delta_rad", 0.0)),
            num_samples=int(data.get("num_samples", 0)),
            last_update_utc=parsed_last_update,
        )

    def save(self, path: Path | None = None) -> None:
        path = path or DEFAULT_MODEL_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(self.to_dict(), handle, indent=2)
                handle.flush()
            tmp_path.replace(path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    @classmethod
    def load(cls, path: Path | None = None) -> "PointingModel":
        path = path or DEFAULT_MODEL_PATH
        if not path.exists():
            return cls()
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return cls()
        return cls.from_dict(data)
