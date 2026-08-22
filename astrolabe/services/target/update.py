import csv
import datetime
import gzip
import json
from pathlib import Path
import socket
import ssl
from urllib.parse import urlparse
from urllib.request import urlopen

from .normalize import normalize_query

HIPPARCOS_CATALOG_ID = "I/239"
BSC_CATALOG_ID = "V/50"

HIPPARCOS_DEFAULT_URLS = [
    "https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat.gz",
    "https://cdsarc.u-strasbg.fr/ftp/cats/I/239/hip_main.dat.gz",
    "https://cdsarc.u-strasbg.fr/ftp/cats/1/239/hip_main.dat.gz",
    "https://cdsarc.cds.unistra.fr/ftp/I/239/version_cd/cats/hip_main.dat.gz",
    "https://cdsarc.cds.unistra.fr/ftp/I/239/version_cd/cats/hip_main.dat",
]

BSC_DEFAULT_URL = (
    "https://vizier.cds.unistra.fr/viz-bin/asu-tsv?"
    "-source=V/50&-out=Name,HD&-out.max=unlimited"
)


def update_hipparcos(
    source: str | None = None,
    output_path: str | None = None,
    max_mag: float | None = None,
    *,
    verify_ssl: bool = True,
    show_progress: bool = False,
) -> dict:
    source = source or ""
    cache_dir = _hip_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    if source:
        data_path = _fetch_to_cache(
            source, cache_dir, verify_ssl=verify_ssl, show_progress=show_progress
        )
        source_used = source
    else:
        data_path, source_used = _fetch_first_available(
            HIPPARCOS_DEFAULT_URLS,
            cache_dir,
            verify_ssl=verify_ssl,
            show_progress=show_progress,
        )
    records = list(_iter_hipparcos_records(data_path, max_mag=max_mag))

    output_path = output_path or _default_hip_subset_path()
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    _write_hip_subset(records, output_file)

    meta = {
        "source": source_used,
        "source_catalog": HIPPARCOS_CATALOG_ID,
        "cache_dir": str(cache_dir),
        "output_path": str(output_file),
        "stars_written": len(records),
        "max_mag": max_mag,
        "updated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    _write_metadata(meta, cache_dir / "metadata.json")
    return meta


def update_bsc_crosswalk(
    source: str | None = None,
    hip_source: str | None = None,
    output_path: str | None = None,
    *,
    verify_ssl: bool = True,
    show_progress: bool = False,
) -> dict:
    cache_dir = _bsc_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    bsc_source = source or BSC_DEFAULT_URL
    bsc_path = _fetch_to_cache(
        bsc_source, cache_dir, verify_ssl=verify_ssl, show_progress=show_progress
    )

    if hip_source:
        hip_path = _fetch_to_cache(
            hip_source, cache_dir, verify_ssl=verify_ssl, show_progress=show_progress
        )
        hip_source_used = hip_source
    else:
        hip_path, hip_source_used = _fetch_first_available(
            HIPPARCOS_DEFAULT_URLS,
            cache_dir,
            verify_ssl=verify_ssl,
            show_progress=show_progress,
        )

    hd_to_hip = _load_hd_to_hip(hip_path)
    aliases = list(_iter_bsc_aliases(bsc_path, hd_to_hip))

    output_path = output_path or _default_bsc_crosswalk_path()
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    aliases_written, ambiguous_aliases_skipped = _write_aliases_csv(
        aliases, output_file
    )

    meta = {
        "source": bsc_source,
        "source_catalog": BSC_CATALOG_ID,
        "hip_source": hip_source_used,
        "hip_source_catalog": HIPPARCOS_CATALOG_ID,
        "cache_dir": str(cache_dir),
        "output_path": str(output_file),
        "aliases_written": aliases_written,
        "ambiguous_aliases_skipped": ambiguous_aliases_skipped,
        "updated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    _write_metadata(meta, cache_dir / "bsc_metadata.json")
    return meta


def _iter_hipparcos_records(path: Path, max_mag: float | None = None):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            record = _parse_hipparcos_line(line)
            if record is None:
                continue
            if max_mag is not None:
                mag = record["mag"]
                if mag is None or mag > max_mag:
                    continue
            yield record


def _parse_hipparcos_line(line: str) -> dict | None:
    if len(line) < 76:
        return None
    hip_id = line[8:14].strip()
    if not hip_id:
        return None
    ra = _parse_float(line[51:63])
    dec = _parse_float(line[64:76])
    if ra is None or dec is None:
        return None
    mag = _parse_float(line[41:46])
    return {
        "hip_id": hip_id,
        "ra_deg": ra,
        "dec_deg": dec,
        "mag": mag,
        "name": f"HIP {hip_id}",
    }


def _load_hd_to_hip(path: Path) -> dict[str, str]:
    opener = gzip.open if path.suffix == ".gz" else open
    mapping: dict[str, str] = {}
    ambiguous: set[str] = set()
    with opener(path, "rt", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if len(line) < 396:
                continue
            hip_id = line[8:14].strip()
            hd = line[390:396].strip()
            if not hip_id or not hd or hd in ambiguous:
                continue
            existing = mapping.get(hd)
            if existing is None:
                mapping[hd] = hip_id
            elif existing != hip_id:
                del mapping[hd]
                ambiguous.add(hd)
    return mapping


def _parse_float(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _write_hip_subset(records: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["hip_id", "ra_deg", "dec_deg", "mag", "name"]
        )
        writer.writeheader()
        for record in sorted(records, key=lambda item: int(item["hip_id"])):
            writer.writerow(record)


def _write_metadata(meta: dict, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2)


def _fetch_first_available(
    sources: list[str], cache_dir: Path, *, verify_ssl: bool, show_progress: bool
) -> tuple[Path, str]:
    errors: list[str] = []
    for candidate in sources:
        try:
            return (
                _fetch_to_cache(
                    candidate,
                    cache_dir,
                    verify_ssl=verify_ssl,
                    show_progress=show_progress,
                ),
                candidate,
            )
        except Exception as exc:
            errors.append(f"{candidate} ({exc})")
    raise FileNotFoundError(
        "No valid Hipparcos source found. Tried: " + "; ".join(errors)
    )


def _fetch_to_cache(
    source: str, cache_dir: Path, *, verify_ssl: bool, show_progress: bool
) -> Path:
    parsed = urlparse(source)
    if parsed.scheme in ("http", "https"):
        filename = Path(parsed.path).name
        if not filename:
            raise ValueError(f"Invalid source URL: {source}")
        target = cache_dir / filename
        context = None
        if not verify_ssl:
            context = ssl._create_unverified_context()
        try:
            with urlopen(source, timeout=30, context=context) as resp:
                total = resp.headers.get("Content-Length")
                total_bytes = int(total) if total and total.isdigit() else None
                data = _read_with_progress(
                    resp, total_bytes, show_progress=show_progress
                )
        except (OSError, socket.timeout):
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


def _hip_cache_dir() -> Path:
    return Path.home() / ".astrolabe" / "cache" / "catalog" / "hipparcos"


def _default_hip_subset_path() -> str:
    return str(Path.home() / ".astrolabe" / "data" / "hip_subset.csv")


def _bsc_cache_dir() -> Path:
    return Path.home() / ".astrolabe" / "cache" / "catalog" / "bsc"


def _default_bsc_crosswalk_path() -> str:
    return str(Path.home() / ".astrolabe" / "data" / "bsc_crosswalk.csv")


def _iter_bsc_aliases(path: Path, hd_to_hip: dict[str, str]):
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = None
        for row in reader:
            if not row:
                continue
            if row[0].startswith("#"):
                continue
            if header is None:
                header = [cell.strip() for cell in row]
                continue
            record = {
                header[i]: row[i].strip() for i in range(min(len(header), len(row)))
            }
            name = record.get("Name", "").strip()
            hd = record.get("HD", "").strip()
            if not name or not hd:
                continue
            hip_id = hd_to_hip.get(hd)
            if not hip_id:
                continue
            for alias in _aliases_from_bsc_name(name):
                yield (alias, hip_id)


def _aliases_from_bsc_name(value: str) -> list[str]:
    """Expand a BSC V/50 ``Name`` field into Bayer and Flamsteed aliases.

    The BSC field combines an optional Flamsteed number, optional three-letter
    Bayer designation (plus component index), and a three-letter constellation.
    Expanded aliases use the IAU Latin genitive form used by Bayer and Flamsteed
    designations. VizieR may preserve or insert whitespace, so parse the compact
    form rather than relying on word boundaries.
    """
    compact = "".join(value.strip().split())
    if len(compact) < 4:
        return []

    const_abbr = compact[-3:].lower()
    const_genitive = _CONSTELLATION_GENITIVE.get(const_abbr)
    if const_genitive is None:
        return []

    designation = compact[:-3]
    split = 0
    while split < len(designation) and designation[split].isdigit():
        split += 1
    flamsteed = designation[:split]
    bayer = designation[split:]

    aliases: list[str] = []
    if bayer:
        greek_abbr = bayer[:3].lower()
        greek_full = _GREEK_ABBR.get(greek_abbr)
        component = bayer[3:]
        if greek_full and (not component or component.isdigit()):
            aliases.append(f"{greek_full}{component} {const_abbr}")
            aliases.append(f"{greek_full}{component} {const_genitive}")

    if flamsteed:
        aliases.append(f"{flamsteed} {const_abbr}")
        aliases.append(f"{flamsteed} {const_genitive}")

    return aliases


def _write_aliases_csv(
    aliases: list[tuple[str, str]], path: Path
) -> tuple[int, int]:
    canonical: dict[str, tuple[str, str]] = {}
    ambiguous: set[str] = set()
    for alias, hip_id in aliases:
        alias = " ".join(alias.strip().lower().split())
        hip_id = hip_id.strip()
        normalized = normalize_query(alias)
        if not normalized or not hip_id or normalized in ambiguous:
            continue

        existing = canonical.get(normalized)
        if existing is not None and existing[1] != hip_id:
            # A Bayer/Flamsteed designation can name a multiple-star system rather
            # than one unique HIP component (for example, 61 Cyg). The two input
            # catalogues do not provide a principled system-primary choice here,
            # so omit ambiguous aliases rather than depending on source order.
            del canonical[normalized]
            ambiguous.add(normalized)
            continue
        if existing is None or alias < existing[0]:
            canonical[normalized] = (alias, hip_id)

    rows = sorted(
        canonical.values(),
        key=lambda item: (normalize_query(item[0]), item[0], item[1]),
    )
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["alias", "hip_id"])
        writer.writeheader()
        for alias, hip_id in rows:
            writer.writerow({"alias": alias, "hip_id": hip_id})
    return len(rows), len(ambiguous)


def _read_with_progress(
    stream, total_bytes: int | None, *, show_progress: bool
) -> bytes:
    if not show_progress:
        return stream.read()
    chunk_size = 64 * 1024
    data = bytearray()
    read_bytes = 0
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        data.extend(chunk)
        read_bytes += len(chunk)
        if total_bytes:
            pct = read_bytes / total_bytes * 100
            print(f"\rDownloading... {pct:5.1f}% ", end="", flush=True)
        else:
            print(
                f"\rDownloading... {read_bytes / (1024 * 1024):.1f} MB ",
                end="",
                flush=True,
            )
    print("\rDownload complete.          ")
    return bytes(data)


_GREEK_ABBR = {
    "alp": "alpha",
    "bet": "beta",
    "gam": "gamma",
    "del": "delta",
    "eps": "epsilon",
    "zet": "zeta",
    "eta": "eta",
    "the": "theta",
    "iot": "iota",
    "kap": "kappa",
    "lam": "lambda",
    "mu": "mu",
    "nu": "nu",
    "xi": "xi",
    "omi": "omicron",
    "pi": "pi",
    "rho": "rho",
    "sig": "sigma",
    "tau": "tau",
    "ups": "upsilon",
    "phi": "phi",
    "chi": "chi",
    "psi": "psi",
    "ome": "omega",
}

_CONSTELLATION_GENITIVE = {
    "and": "andromedae",
    "ant": "antliae",
    "aps": "apodis",
    "aqr": "aquarii",
    "aql": "aquilae",
    "ara": "arae",
    "ari": "arietis",
    "aur": "aurigae",
    "boo": "bootis",
    "cae": "caeli",
    "cam": "camelopardalis",
    "cap": "capricorni",
    "car": "carinae",
    "cas": "cassiopeiae",
    "cen": "centauri",
    "cep": "cephei",
    "cet": "ceti",
    "cha": "chamaeleontis",
    "cir": "circini",
    "cma": "canis majoris",
    "cmi": "canis minoris",
    "cnc": "cancri",
    "col": "columbae",
    "com": "comae berenices",
    "cra": "coronae australis",
    "crb": "coronae borealis",
    "crv": "corvi",
    "crt": "crateris",
    "cru": "crucis",
    "cyg": "cygni",
    "del": "delphini",
    "dor": "doradus",
    "dra": "draconis",
    "equ": "equulei",
    "eri": "eridani",
    "for": "fornacis",
    "gem": "geminorum",
    "gru": "gruis",
    "her": "herculis",
    "hor": "horologii",
    "hya": "hydrae",
    "hyi": "hydri",
    "ind": "indi",
    "lac": "lacertae",
    "leo": "leonis",
    "lmi": "leonis minoris",
    "lep": "leporis",
    "lib": "librae",
    "lup": "lupi",
    "lyn": "lyncis",
    "lyr": "lyrae",
    "men": "mensae",
    "mic": "microscopii",
    "mon": "monocerotis",
    "mus": "muscae",
    "nor": "normae",
    "oct": "octantis",
    "oph": "ophiuchi",
    "ori": "orionis",
    "pav": "pavonis",
    "peg": "pegasi",
    "per": "persei",
    "phe": "phoenicis",
    "pic": "pictoris",
    "psa": "piscis austrini",
    "psc": "piscium",
    "pup": "puppis",
    "pyx": "pyxidis",
    "ret": "reticuli",
    "scl": "sculptoris",
    "sco": "scorpii",
    "sct": "scuti",
    "ser": "serpentis",
    "sex": "sextantis",
    "sge": "sagittae",
    "sgr": "sagittarii",
    "tau": "tauri",
    "tel": "telescopii",
    "tra": "trianguli australis",
    "tri": "trianguli",
    "tuc": "tucanae",
    "uma": "ursae majoris",
    "umi": "ursae minoris",
    "vel": "velorum",
    "vir": "virginis",
    "vol": "volantis",
    "vul": "vulpeculae",
}
