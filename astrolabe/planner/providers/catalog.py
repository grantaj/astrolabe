from dataclasses import dataclass
import csv
from pathlib import Path

from .base import CatalogProvider
from astrolabe.planner.types import Target


@dataclass
class LocalCuratedCatalogProvider(CatalogProvider):
    name: str = "curated"
    catalog_path: Path | None = None

    def _resolve_path(self) -> Path:
        if self.catalog_path is not None:
            return self.catalog_path
        repo_root = Path(__file__).resolve().parents[3]
        return repo_root / "data" / "catalog_curated.csv"

    def list_targets(self):
        path = self._resolve_path()
        if not path.exists():
            raise FileNotFoundError(f"Curated catalog not found: {path}")
        targets: list[Target] = []
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                tags = [
                    t.strip() for t in (row.get("tags") or "").split(";") if t.strip()
                ]
                targets.append(
                    Target(
                        id=row["id"].strip(),
                        name=row["name"].strip(),
                        common_name=_parse_optional(row.get("common_name")),
                        messier_id=_parse_optional(row.get("messier_id")),
                        caldwell_id=_parse_optional(row.get("caldwell_id")),
                        ra_deg=float(row["ra_deg"]),
                        dec_deg=float(row["dec_deg"]),
                        type=row["type"].strip(),
                        mag=_parse_float(row.get("mag")),
                        size_arcmin=_parse_float(row.get("size_arcmin")),
                        size_major_arcmin=_parse_float(row.get("size_major_arcmin")),
                        size_minor_arcmin=_parse_float(row.get("size_minor_arcmin")),
                        surface_brightness=_parse_float(row.get("surface_brightness")),
                        tags=tuple(tags),
                    )
                )
        return targets


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return float(value)


def _parse_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None
