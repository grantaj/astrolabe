import csv
import datetime
import gzip
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen
import socket
import ssl

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
    _write_aliases_csv(aliases, output_file)

    meta = {
        "source": bsc_source,
        "hip_source": hip_source_used,
        "cache_dir": str(cache_dir),
        "output_path": str(output_file),
        "aliases_written": len(aliases),
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
    with opener(path, "rt", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if len(line) < 396:
                continue
            hip_id = line[8:14].strip()
            hd = line[390:396].strip()
            if not hip_id or not hd:
                continue
            if hd not in mapping:
                mapping[hd] = hip_id
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
        for record in records:
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
    value = value.strip()
    if not value:
        return []
    parts = value.split()
    if len(parts) < 2:
        return []
    first = parts[0].strip().lower()
    const = parts[1].strip().lower()
    const = "".join(ch for ch in const if ch.isalpha())
    const_abbr = const[:3]
    if not const_abbr:
        return []
    const_full = _CONSTELLATION_FULL.get(const_abbr)

    greek_abbr = "".join(ch for ch in first if ch.isalpha())
    greek_idx = "".join(ch for ch in first if ch.isdigit())
    greek_full = _GREEK_ABBR.get(greek_abbr, greek_abbr)
    if not greek_full:
        return []
    alias = f"{greek_full}{greek_idx} {const_abbr}"
    aliases = [alias]
    if const_full:
        aliases.append(f"{greek_full}{greek_idx} {const_full}")
    return aliases


def _write_aliases_csv(aliases: list[tuple[str, str]], path: Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["alias", "hip_id"])
        writer.writeheader()
        for alias, hip_id in aliases:
            writer.writerow({"alias": alias, "hip_id": hip_id})


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

_CONSTELLATION_FULL = {
    "and": "andromeda",
    "ant": "antlia",
    "aps": "apus",
    "aqr": "aquarius",
    "aql": "aquila",
    "ara": "ara",
    "ari": "aries",
    "aur": "auriga",
    "boo": "bootes",
    "cae": "caelum",
    "cam": "camelopardalis",
    "cap": "capricornus",
    "car": "carina",
    "cas": "cassiopeia",
    "cen": "centaurus",
    "cep": "cepheus",
    "cet": "cetus",
    "cha": "chamaeleon",
    "cir": "circinus",
    "cma": "canis major",
    "cmi": "canis minor",
    "cnc": "cancer",
    "col": "columba",
    "com": "coma berenices",
    "cra": "corona australis",
    "crb": "corona borealis",
    "crv": "corvus",
    "crt": "crater",
    "cru": "crux",
    "cyg": "cygnus",
    "del": "delphinus",
    "dor": "dorado",
    "dra": "draco",
    "equ": "equuleus",
    "eri": "eridanus",
    "for": "fornax",
    "gem": "gemini",
    "gru": "grus",
    "her": "hercules",
    "hor": "horologium",
    "hya": "hydra",
    "hyi": "hydrus",
    "ind": "indus",
    "lac": "lacerta",
    "leo": "leo",
    "lmi": "leo minor",
    "lep": "lepus",
    "lib": "libra",
    "lup": "lupus",
    "lyn": "lynx",
    "lyr": "lyra",
    "men": "mensa",
    "mic": "microscopium",
    "mon": "monoceros",
    "mus": "musca",
    "nor": "norma",
    "oct": "octans",
    "oph": "ophiuchus",
    "ori": "orion",
    "pav": "pavo",
    "peg": "pegasus",
    "per": "perseus",
    "phe": "phoenix",
    "pic": "pictor",
    "psa": "piscis austrinus",
    "psc": "pisces",
    "pup": "puppis",
    "pyx": "pyxis",
    "ret": "reticulum",
    "scl": "sculptor",
    "sco": "scorpius",
    "sct": "scutum",
    "ser": "serpens",
    "sex": "sextans",
    "sge": "sagitta",
    "sgr": "sagittarius",
    "tau": "taurus",
    "tel": "telescopium",
    "tra": "triangulum australe",
    "tri": "triangulum",
    "tuc": "tucana",
    "uma": "ursa major",
    "umi": "ursa minor",
    "vel": "vela",
    "vir": "virgo",
    "vol": "volans",
    "vul": "vulpecula",
}
