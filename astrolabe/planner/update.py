import csv
import datetime
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.error import HTTPError
from urllib.request import urlopen

from .types import Target

DEFAULT_OPENNGC_VERSION = "v20231203"
OPENNGC_BASE_URL = "https://raw.githubusercontent.com/mattiaverga/OpenNGC/{version}/"
OPENNGC_CANDIDATES = {
    "NGC.csv": ("database_files/NGC.csv", "NGC.csv"),
    "IC.csv": ("database_files/IC.csv", "IC.csv"),
    "addendum.csv": ("database_files/addendum.csv", "addendum.csv"),
}


def update_catalog(source: str | None = None, version: str | None = None, output_path: str | None = None) -> dict:
    version = version or DEFAULT_OPENNGC_VERSION
    cache_dir = _cache_dir(version)
    cache_dir.mkdir(parents=True, exist_ok=True)

    sources = _resolve_sources(source, version)
    cached_files = []
    try:
        for item in sources:
            cached_files.append(_fetch_to_cache(item, cache_dir))
    except HTTPError as e:
        if source is None and version != "master" and e.code == 404:
            version = "master"
            cache_dir = _cache_dir(version)
            cache_dir.mkdir(parents=True, exist_ok=True)
            sources = _resolve_sources(source, version)
            cached_files = []
            for item in sources:
                cached_files.append(_fetch_to_cache(item, cache_dir))
        else:
            raise

    targets = []
    for path in cached_files:
        targets.extend(_parse_opengnc_csv(path))

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


def _resolve_sources(source: str | None, version: str) -> list[tuple[str, ...] | str]:
    if not source:
        base = OPENNGC_BASE_URL.format(version=version)
        return [tuple(base + path for path in paths) for paths in OPENNGC_CANDIDATES.values()]
    if source.lower().endswith(".csv"):
        return [source]
    if source.startswith("http://") or source.startswith("https://"):
        base = source.rstrip("/") + "/"
        return [tuple(base + path for path in paths) for paths in OPENNGC_CANDIDATES.values()]
    path = Path(source)
    if path.is_dir():
        return [tuple(str(path / p) for p in paths) for paths in OPENNGC_CANDIDATES.values()]
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
        with urlopen(source) as resp:
            data = resp.read()
        target.write_bytes(data)
        return target
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Source not found: {source}")
    target = cache_dir / path.name
    if path.resolve() != target.resolve():
        target.write_bytes(path.read_bytes())
    return target


def _parse_opengnc_csv(path: Path) -> list[Target]:
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

            vmag = _parse_float(_safe_get(row, 10))
            bmag = _parse_float(_safe_get(row, 9))
            mag = vmag if vmag is not None else bmag
            surf = _parse_float(_safe_get(row, 14))

            target = Target(
                id=_normalize_id(name),
                name=name,
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                type=_map_type(obj_type),
                mag=mag,
                size_arcmin=size_arcmin,
                surface_brightness=surf,
                tags=_tags_from_name(name),
            )
            targets.append(target)
    return targets


def _curate_targets(targets: list[Target]) -> list[Target]:
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
        curated.append(
            Target(
                id=target.id,
                name=target.name,
                ra_deg=target.ra_deg,
                dec_deg=target.dec_deg,
                type=target.type,
                mag=target.mag,
                size_arcmin=target.size_arcmin,
                surface_brightness=target.surface_brightness,
                tags=sorted(set(tags)),
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
                "ra_deg",
                "dec_deg",
                "type",
                "mag",
                "size_arcmin",
                "surface_brightness",
                "tags",
            ]
        )
        for t in targets:
            writer.writerow(
                [
                    t.id,
                    t.name,
                    f"{t.ra_deg:.6f}",
                    f"{t.dec_deg:.6f}",
                    t.type,
                    "" if t.mag is None else f"{t.mag:.2f}",
                    "" if t.size_arcmin is None else f"{t.size_arcmin:.2f}",
                    "" if t.surface_brightness is None else f"{t.surface_brightness:.2f}",
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


def _safe_get(row: list[str], idx: int) -> str | None:
    if idx >= len(row):
        return None
    return row[idx].strip()


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
    return mapping.get(t, "other")


def _is_southern_showpiece(target: Target) -> bool:
    if target.dec_deg > -30.0:
        return False
    if target.mag is not None and target.mag <= 6.5:
        return True
    if target.size_arcmin is not None and target.size_arcmin >= 20.0:
        return True
    return False
