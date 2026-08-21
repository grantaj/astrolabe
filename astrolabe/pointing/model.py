from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any


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
