import csv
from pathlib import Path

from .normalize import normalize_query
from .types import TargetRecord


class TargetIndex:
    def __init__(self) -> None:
        self._id_index: dict[str, TargetRecord] = {}
        self._alias_index: dict[str, TargetRecord] = {}

    def add_record(self, record: TargetRecord) -> None:
        self._id_index[normalize_query(record.id)] = record
        self._alias_index[normalize_query(record.name)] = record
        if record.aliases:
            for alias in record.aliases:
                self._alias_index[normalize_query(alias)] = record

    def get_by_id(self, key: str) -> TargetRecord | None:
        return self._id_index.get(normalize_query(key))

    def get_by_alias(self, key: str) -> TargetRecord | None:
        return self._alias_index.get(normalize_query(key))

    def iter_aliases(self):
        return self._alias_index.items()


def load_catalog_csv(path: Path) -> list[TargetRecord]:
    if not path.exists():
        raise FileNotFoundError(f"Catalog not found: {path}")

    records: list[TargetRecord] = []
    with open(path, "r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            records.append(
                TargetRecord(
                    id=row["id"].strip(),
                    name=row["name"].strip(),
                    ra_deg=float(row["ra_deg"]),
                    dec_deg=float(row["dec_deg"]),
                    target_type=(row.get("type") or "").strip() or None,
                    mag=_parse_float(row.get("mag")),
                    aliases=_collect_aliases(row),
                )
            )
    return records


def load_hip_subset_csv(path: Path) -> list[TargetRecord]:
    if not path.exists():
        raise FileNotFoundError(f"Hipparcos subset not found: {path}")

    records: list[TargetRecord] = []
    with open(path, "r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            hip_id = row["hip_id"].strip()
            records.append(
                TargetRecord(
                    id=f"HIP {hip_id}",
                    name=row.get("name", hip_id).strip() or f"HIP {hip_id}",
                    ra_deg=float(row["ra_deg"]),
                    dec_deg=float(row["dec_deg"]),
                    target_type="star",
                    mag=_parse_float(row.get("mag")),
                )
            )
    return records


def load_alias_csv(path: Path) -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"Alias table not found: {path}")

    aliases: dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            alias = row["alias"].strip()
            hip_id = row["hip_id"].strip()
            aliases[alias] = hip_id
    return aliases


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    return float(value) if value else None


def _collect_aliases(row: dict[str, str]) -> list[str] | None:
    aliases: list[str] = []
    for key in ("common_name", "messier_id", "caldwell_id"):
        value = (row.get(key) or "").strip()
        if value:
            aliases.append(value)
    return aliases or None
