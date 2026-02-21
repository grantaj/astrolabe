import csv
import datetime
import json
import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
import socket

from .types import Target

DEFAULT_OPENNGC_VERSION = "master"
OPENNGC_BASE_URL = "https://raw.githubusercontent.com/mattiaverga/OpenNGC/{version}/"
OPENNGC_REQUIRED = {
    "NGC.csv": ("database_files/NGC.csv",),
}
OPENNGC_OPTIONAL = {
    "addendum.csv": ("database_files/addendum.csv",),
}


def update_catalog(
    source: str | None = None,
    version: str | None = None,
    output_path: str | None = None,
) -> dict:
    version = version or DEFAULT_OPENNGC_VERSION
    cache_dir = _cache_dir(version)
    cache_dir.mkdir(parents=True, exist_ok=True)

    try:
        cached_files = _fetch_all_sources(source, version, cache_dir)
    except (HTTPError, FileNotFoundError) as e:
        if source is None and version != "master" and _is_not_found(e):
            version = "master"
            cache_dir = _cache_dir(version)
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached_files = _fetch_all_sources(source, version, cache_dir)
        else:
            raise

    targets = []
    for path in cached_files:
        targets.extend(_parse_openngc_csv(path))

    curated = _curate_targets(targets)
    output_path = output_path or _default_catalog_path()
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    _write_curated_csv(curated, output_file)

    meta = {
        "source": source or f"OpenNGC {version}",
        "version": version,
        "cache_dir": str(cache_dir),
        "output_path": str(output_file),
        "targets_written": len(curated),
        "updated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    _write_metadata(meta, cache_dir / "metadata.json")
    return meta


def _resolve_sources(
    source: str | None, version: str, candidates: dict[str, tuple[str, ...]]
) -> list[tuple[str, ...] | str]:
    if not source:
        base = OPENNGC_BASE_URL.format(version=version)
        return [tuple(base + path for path in paths) for paths in candidates.values()]
    if source.lower().endswith(".csv"):
        return [source]
    if source.startswith("http://") or source.startswith("https://"):
        base = source.rstrip("/") + "/"
        return [tuple(base + path for path in paths) for paths in candidates.values()]
    path = Path(source)
    if path.is_dir():
        return [tuple(str(path / p) for p in paths) for paths in candidates.values()]
    return [source]


def _fetch_to_cache(source: str | tuple[str, ...], cache_dir: Path) -> Path:
    if isinstance(source, tuple):
        errors = []
        for candidate in source:
            try:
                return _fetch_to_cache(candidate, cache_dir)
            except (HTTPError, FileNotFoundError) as e:
                errors.append(f"{candidate} ({e})")
        raise FileNotFoundError("No valid source found. Tried: " + "; ".join(errors))

    parsed = urlparse(source)
    if parsed.scheme in ("http", "https"):
        filename = Path(parsed.path).name
        if not filename:
            raise ValueError(f"Invalid source URL: {source}")
        target = cache_dir / filename
        # Set a timeout to avoid hanging indefinitely if the remote host is
        # unresponsive. Surface network errors to the caller for handling.
        try:
            with urlopen(source, timeout=15) as resp:
                data = resp.read()
        except (URLError, socket.timeout) as e:
            raise
        target.write_bytes(data)
        return target
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Source not found: {source}")
    target = cache_dir / path.name
    if path.resolve() != target.resolve():
        target.write_bytes(path.read_bytes())
    return target


def _fetch_all_sources(source: str | None, version: str, cache_dir: Path) -> list[Path]:
    cached_files: list[Path] = []
    required_sources = _resolve_sources(source, version, OPENNGC_REQUIRED)
    for item in required_sources:
        cached_files.append(_fetch_to_cache(item, cache_dir))

    optional_sources = _resolve_sources(source, version, OPENNGC_OPTIONAL)
    for item in optional_sources:
        try:
            cached_files.append(_fetch_to_cache(item, cache_dir))
        except (HTTPError, FileNotFoundError):
            continue
    return cached_files


def _parse_openngc_csv(path: Path) -> list[Target]:
    targets: list[Target] = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        sample = f.read(4096)
        f.seek(0)
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        reader = csv.reader(f, delimiter=delimiter)
        for row in reader:
            if not row or row[0].startswith("#"):
                continue
            if len(row) < 5:
                continue
            name = row[0].strip()
            if not name:
                continue
            obj_type = row[1].strip()
            ra_raw = row[2].strip()
            dec_raw = row[3].strip()
            ra_deg = _parse_ra_to_deg(ra_raw)
            dec_deg = _parse_dec_to_deg(dec_raw)
            if ra_deg is None or dec_deg is None:
                continue

            maj_ax = _parse_float(_safe_get(row, 5))
            min_ax = _parse_float(_safe_get(row, 6))
            size_arcmin = _estimate_size_arcmin(maj_ax, min_ax)
            size_major_arcmin = maj_ax
            size_minor_arcmin = min_ax

            # OpenNGC columns: B-Mag=8, V-Mag=9, SurfBr=13
            bmag = _parse_float(_safe_get(row, 8))
            vmag = _parse_float(_safe_get(row, 9))
            mag = vmag if vmag is not None else bmag
            surf = _parse_float(_safe_get(row, 13))

            messier_id = _parse_messier_id(_safe_get(row, 23))
            common_name = _parse_common_name(_safe_get(row, 28))
            tags = _tags_from_name(name)
            if messier_id:
                tags.append("messier")
            target = Target(
                id=_normalize_id(name),
                name=name,
                common_name=common_name,
                messier_id=messier_id,
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                type=_map_type(obj_type),
                mag=mag,
                size_arcmin=size_arcmin,
                size_major_arcmin=size_major_arcmin,
                size_minor_arcmin=size_minor_arcmin,
                surface_brightness=surf,
                tags=tuple(tags),
            )
            targets.append(target)
    return targets


def _curate_targets(targets: list[Target]) -> list[Target]:
    caldwell_map = _load_caldwell_map()
    curated = []
    for target in targets:
        if target.type in ("duplicate", "nonexistent", "other"):
            continue
        if target.mag is not None and target.mag > 12.5:
            if target.size_arcmin is None or target.size_arcmin < 5.0:
                continue
        if target.size_arcmin is not None:
            if target.size_arcmin < 0.5 or target.size_arcmin > 200.0:
                continue
        tags = list(target.tags)
        if _is_southern_showpiece(target):
            tags.append("southern_showpiece")
        if _is_messier_showpiece(target):
            tags.append("showpiece")
        normalized_id = _normalize_catalog_id(target.id)
        caldwell_id = caldwell_map.get(normalized_id) if normalized_id else None
        if caldwell_id:
            tags.append("caldwell")
        curated.append(
            Target(
                id=target.id,
                name=target.name,
                ra_deg=target.ra_deg,
                dec_deg=target.dec_deg,
                type=target.type,
                mag=target.mag,
                size_arcmin=target.size_arcmin,
                size_major_arcmin=target.size_major_arcmin,
                size_minor_arcmin=target.size_minor_arcmin,
                surface_brightness=target.surface_brightness,
                common_name=target.common_name,
                messier_id=target.messier_id,
                caldwell_id=caldwell_id,
                tags=tuple(sorted(set(tags))),
            )
        )
    return curated


def _write_curated_csv(targets: list[Target], path: Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "id",
                "name",
                "common_name",
                "messier_id",
                "caldwell_id",
                "ra_deg",
                "dec_deg",
                "type",
                "mag",
                "size_arcmin",
                "size_major_arcmin",
                "size_minor_arcmin",
                "surface_brightness",
                "tags",
            ]
        )
        for t in targets:
            writer.writerow(
                [
                    t.id,
                    t.name,
                    "" if t.common_name is None else t.common_name,
                    "" if t.messier_id is None else t.messier_id,
                    "" if t.caldwell_id is None else t.caldwell_id,
                    f"{t.ra_deg:.6f}",
                    f"{t.dec_deg:.6f}",
                    t.type,
                    "" if t.mag is None else f"{t.mag:.2f}",
                    "" if t.size_arcmin is None else f"{t.size_arcmin:.2f}",
                    "" if t.size_major_arcmin is None else f"{t.size_major_arcmin:.2f}",
                    "" if t.size_minor_arcmin is None else f"{t.size_minor_arcmin:.2f}",
                    ""
                    if t.surface_brightness is None
                    else f"{t.surface_brightness:.2f}",
                    ";".join(t.tags),
                ]
            )


def _write_metadata(meta: dict, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def _cache_dir(version: str) -> Path:
    base = Path.home() / ".astrolabe" / "cache" / "catalog" / "opengnc" / version
    return base


def _default_catalog_path() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    return str(repo_root / "data" / "catalog_curated.csv")


def _load_caldwell_map() -> dict[str, str]:
    path = Path(__file__).resolve().parents[2] / "data" / "caldwell.csv"
    if not path.exists():
        return {}
    mapping: dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            caldwell_id = row.get("caldwell_id")
            object_id = row.get("object_id")
            if not caldwell_id or not object_id:
                continue
            norm = _normalize_catalog_id(object_id)
            if norm:
                mapping[norm] = caldwell_id
    return mapping


def _is_not_found(exc: Exception) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code == 404
    return isinstance(exc, FileNotFoundError)


def _safe_get(row: list[str], idx: int) -> str | None:
    if idx >= len(row):
        return None
    return row[idx].strip()


def _normalize_catalog_id(value: str) -> str | None:
    value = value.strip().upper()
    if value.startswith("NGC"):
        num = re.findall(r"\d+", value)
        if not num:
            return None
        return f"NGC{int(num[0]):04d}"
    if value.startswith("IC"):
        num = re.findall(r"\d+", value)
        if not num:
            return None
        return f"IC{int(num[0]):04d}"
    return None


def _parse_ra_to_deg(value: str) -> float | None:
    if not value:
        return None
    if ":" in value:
        parts = value.split(":")
        if len(parts) < 3:
            return None
        h = float(parts[0])
        m = float(parts[1])
        s = float(parts[2])
        hours = h + m / 60.0 + s / 3600.0
        return hours * 15.0
    try:
        return float(value)
    except ValueError:
        return None


def _parse_dec_to_deg(value: str) -> float | None:
    if not value:
        return None
    if ":" in value:
        sign = -1.0 if value.strip().startswith("-") else 1.0
        parts = value.replace("+", "").replace("-", "").split(":")
        if len(parts) < 3:
            return None
        d = float(parts[0])
        m = float(parts[1])
        s = float(parts[2])
        deg = d + m / 60.0 + s / 3600.0
        return sign * deg
    try:
        return float(value)
    except ValueError:
        return None


def _parse_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _estimate_size_arcmin(maj_ax: float | None, min_ax: float | None) -> float | None:
    if maj_ax is None and min_ax is None:
        return None
    if maj_ax is None:
        return min_ax
    if min_ax is None:
        return maj_ax
    return (maj_ax + min_ax) / 2.0


def _normalize_id(name: str) -> str:
    return name.replace(" ", "")


def _tags_from_name(name: str) -> list[str]:
    tags = []
    if name.startswith("M") and name[1:].strip().isdigit():
        tags.append("messier")
    return tags


def _parse_common_name(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.replace("|", ",")
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    if not parts:
        return None
    return parts[0]


def _parse_messier_id(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return f"M{int(value)}"
    if value.upper().startswith("M"):
        return value.upper()
    return None


def _map_type(opengnc_type: str) -> str:
    t = opengnc_type.strip().upper()
    mapping = {
        "G": "galaxy",
        "GCL": "globular_cluster",
        "OC": "open_cluster",
        "PN": "planetary_nebula",
        "EN": "emission_nebula",
        "RN": "reflection_nebula",
        "DN": "dark_nebula",
        "SNR": "supernova_remnant",
        "AST": "asterism",
        "CL": "cluster",
        "GALCL": "galaxy_cluster",
        "GALGRP": "galaxy_group",
        "GALPAIR": "galaxy_pair",
        "STAR": "star",
        "QSO": "quasar",
        "NOV": "nova",
        "NONEX": "nonexistent",
        "DUP": "duplicate",
    }
    if t in mapping:
        return mapping[t]
    if "CL" in t and "N" in t:
        return "emission_nebula"
    if "HII" in t:
        return "emission_nebula"
    if "PN" in t:
        return "planetary_nebula"
    return "other"


def _is_southern_showpiece(target: Target) -> bool:
    if target.dec_deg > -30.0:
        return False
    if target.mag is not None and target.mag <= 6.5:
        return True
    if target.size_arcmin is not None and target.size_arcmin >= 20.0:
        return True
    return False


def _is_messier_showpiece(target: Target) -> bool:
    if target.messier_id is None:
        return False
    if target.mag is not None and target.mag <= 6.5:
        return True
    if target.size_arcmin is not None and target.size_arcmin >= 60.0:
        return True
    return False
