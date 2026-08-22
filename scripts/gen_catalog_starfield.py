#!/usr/bin/env python3
"""Generate a synthetic FITS star field from a local star catalogue.

Defaults model a QHY5III462 guide camera on a 120mm guide scope:
- Sensor: 1920x1080, 2.9um pixels
- Focal length: 120mm (wide field guiding)
- Pixel scale: ~5.0 arcsec/pixel
- FOV: ~2.66 deg x 1.50 deg

All angles in this tool are degrees, matching FITS WCS; nothing here feeds
Astrolabe's radian kernels.

Catalogue data must be present locally; this tool never touches the network.
It reads, in order of preference, a Tycho-2 directory (`tyc2.dat.*.gz`), a HYG
CSV export, or a prepared `.npz` cache with `ra`/`dec`/`mag` arrays.

FITS writing uses Astrolabe's narrow FITS boundary (`astrolabe.camera.pixels`).
The TAN/gnomonic projection below is deliberately tool-local: it exists only to
place catalogue stars on a synthetic sensor, and is not an Astrolabe WCS
subsystem.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from astrolabe.camera.pixels import write_fits_image


class NoCatalogError(Exception):
    """No local star catalogue was available for the requested field."""


@dataclass(frozen=True)
class Field:
    """Synthetic sensor geometry and catalogue selection limits."""

    ra_center_deg: float = 266.4
    dec_center_deg: float = -29.0
    width_px: int = 1920
    height_px: int = 1080
    pixel_size_um: float = 2.9
    focal_length_mm: float = 120.0
    mag_limit: float = 18.0
    max_stars: int = 1000

    @property
    def pixel_scale_arcsec(self) -> float:
        return 206.265 * self.pixel_size_um / self.focal_length_mm

    @property
    def fov_x_deg(self) -> float:
        return self.width_px * self.pixel_scale_arcsec / 3600.0

    @property
    def fov_y_deg(self) -> float:
        return self.height_px * self.pixel_scale_arcsec / 3600.0

    @property
    def radius_deg(self) -> float:
        return math.hypot(self.fov_x_deg, self.fov_y_deg) / 2.0

    @property
    def crpix(self) -> tuple[float, float]:
        """FITS 1-based reference pixel, kept at ``w / 2`` rather than the centred ``(w + 1) / 2`` so removing astropy does not change generated output."""
        return (self.width_px / 2.0, self.height_px / 2.0)

    @property
    def cdelt(self) -> tuple[float, float]:
        scale_deg = self.pixel_scale_arcsec / 3600.0
        return (-scale_deg, scale_deg)


@dataclass(frozen=True)
class Catalog:
    ra_deg: np.ndarray
    dec_deg: np.ndarray
    mag: np.ndarray

    def __len__(self) -> int:
        return int(self.ra_deg.size)


def tan_world_to_pixel(
    ra_deg: np.ndarray,
    dec_deg: np.ndarray,
    field: Field,
) -> tuple[np.ndarray, np.ndarray]:
    """Project world coordinates onto zero-based pixel coordinates (RA---TAN)."""

    ra = np.deg2rad(np.asarray(ra_deg, dtype=float))
    dec = np.deg2rad(np.asarray(dec_deg, dtype=float))
    ra0 = math.radians(field.ra_center_deg)
    dec0 = math.radians(field.dec_center_deg)

    delta_ra = ra - ra0
    cos_c = np.sin(dec0) * np.sin(dec) + np.cos(dec0) * np.cos(dec) * np.cos(delta_ra)
    with np.errstate(divide="ignore", invalid="ignore"):
        xi = np.cos(dec) * np.sin(delta_ra) / cos_c
        eta = (
            np.cos(dec0) * np.sin(dec) - np.sin(dec0) * np.cos(dec) * np.cos(delta_ra)
        ) / cos_c

    crpix1, crpix2 = field.crpix
    cdelt1, cdelt2 = field.cdelt
    x = (crpix1 - 1.0) + np.rad2deg(xi) / cdelt1
    y = (crpix2 - 1.0) + np.rad2deg(eta) / cdelt2
    return x, y


def wcs_header_cards(field: Field) -> dict[str, float | str]:
    # No DATE-OBS: a wall-clock stamp would make otherwise identical runs differ.
    crpix1, crpix2 = field.crpix
    cdelt1, cdelt2 = field.cdelt
    return {
        "CTYPE1": "RA---TAN",
        "CTYPE2": "DEC--TAN",
        "CRPIX1": crpix1,
        "CRPIX2": crpix2,
        "CRVAL1": field.ra_center_deg,
        "CRVAL2": field.dec_center_deg,
        "CDELT1": cdelt1,
        "CDELT2": cdelt2,
    }


def _separation_deg(field: Field, ra_deg, dec_deg):
    """Angular separation from the field centre, in degrees.

    ``util.math.angular_separation_rad`` is scalar-only; the HYG/cache paths need arrays.
    """
    ra = np.deg2rad(ra_deg)
    dec = np.deg2rad(dec_deg)
    ra0 = math.radians(field.ra_center_deg)
    dec0 = math.radians(field.dec_center_deg)
    cos_sep = np.sin(dec0) * np.sin(dec) + np.cos(dec0) * np.cos(dec) * np.cos(ra - ra0)
    return np.rad2deg(np.arccos(np.clip(cos_sep, -1.0, 1.0)))


def _cone_mask(field: Field, ra_deg: np.ndarray, dec_deg: np.ndarray) -> np.ndarray:
    return _separation_deg(field, ra_deg, dec_deg) <= field.radius_deg


def _tycho2_magnitude(line: str) -> float | None:
    for column in (line[123:129], line[110:116]):
        text = column.strip()
        if text:
            try:
                return float(text)
            except ValueError:
                return None
    return None


def load_tycho2(field: Field, tycho_dir: Path) -> Catalog:
    ra_list: list[float] = []
    dec_list: list[float] = []
    mag_list: list[float] = []

    for path in sorted(tycho_dir.glob("tyc2.dat.*.gz")):
        with gzip.open(path, "rt", encoding="ascii", errors="ignore") as handle:
            for line in handle:
                mag = _tycho2_magnitude(line)
                if mag is None or mag > field.mag_limit:
                    continue
                try:
                    ra = float(line[15:27])
                    dec = float(line[28:40])
                except ValueError:
                    continue
                if _separation_deg(field, ra, dec) > field.radius_deg:
                    continue
                ra_list.append(ra)
                dec_list.append(dec)
                mag_list.append(mag)

    return Catalog(
        ra_deg=np.array(ra_list, dtype=float),
        dec_deg=np.array(dec_list, dtype=float),
        mag=np.array(mag_list, dtype=float),
    )


def load_hyg(field: Field, hyg_path: Path) -> Catalog:
    ra_list: list[float] = []
    dec_list: list[float] = []
    mag_list: list[float] = []
    with hyg_path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                mag = float(row["mag"])
                if mag > field.mag_limit:
                    continue
                # HYG 'ra' is in hours; 'rarad' is preferred where present.
                if row.get("rarad") and row.get("decrad"):
                    ra = math.degrees(float(row["rarad"]))
                    dec = math.degrees(float(row["decrad"]))
                else:
                    ra = float(row["ra"]) * 15.0
                    dec = float(row["dec"])
            except (KeyError, TypeError, ValueError):
                continue
            ra_list.append(ra)
            dec_list.append(dec)
            mag_list.append(mag)

    ra_arr = np.array(ra_list, dtype=float)
    dec_arr = np.array(dec_list, dtype=float)
    mag_arr = np.array(mag_list, dtype=float)
    mask = _cone_mask(field, ra_arr, dec_arr)
    return Catalog(ra_deg=ra_arr[mask], dec_deg=dec_arr[mask], mag=mag_arr[mask])


def load_cache(field: Field, cache_path: Path) -> Catalog:
    data = np.load(cache_path)
    ra_arr = np.asarray(data["ra"], dtype=float)
    dec_arr = np.asarray(data["dec"], dtype=float)
    mag_arr = np.asarray(data["mag"], dtype=float)
    keep = _cone_mask(field, ra_arr, dec_arr) & (mag_arr <= field.mag_limit)
    return Catalog(ra_deg=ra_arr[keep], dec_deg=dec_arr[keep], mag=mag_arr[keep])


_NO_CATALOG_MESSAGE = (
    "No local star catalogue found. This tool does not query catalogues over the "
    "network. Provide one of:\n"
    "  - a Tycho-2 directory of tyc2.dat.*.gz files (see scripts/install-tycho2.sh), "
    "passed with --tycho-dir;\n"
    "  - a HYG CSV export (https://astronexus.com/hyg), passed with --hyg;\n"
    "  - a prepared .npz cache with 'ra', 'dec' and 'mag' arrays, passed with --cache."
)


def load_catalog(
    field: Field,
    *,
    tycho_dir: Path,
    hyg_path: Path,
    cache_path: Path,
) -> tuple[Catalog, str]:
    """Load the first available local catalogue, brightest stars first."""

    if tycho_dir.is_dir() and any(tycho_dir.glob("tyc2.dat.*.gz")):
        catalog, source = load_tycho2(field, tycho_dir), f"Tycho-2 ({tycho_dir})"
    elif hyg_path.is_file():
        catalog, source = load_hyg(field, hyg_path), f"HYG ({hyg_path})"
    elif cache_path.is_file():
        catalog, source = load_cache(field, cache_path), f"cache ({cache_path})"
    else:
        raise NoCatalogError(_NO_CATALOG_MESSAGE)

    order = np.argsort(catalog.mag, kind="stable")[: field.max_stars]
    return (
        Catalog(
            ra_deg=catalog.ra_deg[order],
            dec_deg=catalog.dec_deg[order],
            mag=catalog.mag[order],
        ),
        source,
    )


_MAG_ZERO_POINT = 10.0
_FLUX_AT_MAG0 = 60000.0
_BASE_SIGMA = 1.6
_BACKGROUND_LEVEL = 800.0
_READ_NOISE = 4.0
_TARGET_MAX = 60000.0


def render_field(field: Field, catalog: Catalog, *, seed: int) -> np.ndarray:
    """Render a deterministic 16-bit star field for the given catalogue."""

    image = np.zeros((field.height_px, field.width_px), dtype=np.float32)
    y_grid, x_grid = np.ogrid[: field.height_px, : field.width_px]
    xs, ys = tan_world_to_pixel(catalog.ra_deg, catalog.dec_deg, field)

    for x_px, y_px, mag in zip(xs, ys, catalog.mag):
        if not (np.isfinite(x_px) and np.isfinite(y_px)):
            continue
        x = int(round(float(x_px)))
        y = int(round(float(y_px)))
        if not (0 <= x < field.width_px and 0 <= y < field.height_px):
            continue
        flux = _FLUX_AT_MAG0 * 10 ** (-0.4 * (mag - _MAG_ZERO_POINT))
        sigma = _BASE_SIGMA + 0.15 * max(mag - _MAG_ZERO_POINT, 0.0)
        image += flux * np.exp(
            -((x_grid - x) ** 2 + (y_grid - y) ** 2) / (2 * sigma**2)
        )

    rng = np.random.default_rng(seed)
    image += _BACKGROUND_LEVEL
    image += rng.normal(0.0, _READ_NOISE, image.shape)

    # Scale signal above background for viewer visibility without amplifying read noise.
    signal = image - _BACKGROUND_LEVEL
    peak = float(signal.max())
    if peak > 0:
        image = _BACKGROUND_LEVEL + signal * (_TARGET_MAX / peak)
    return np.clip(image, 0, 65535).astype(np.uint16)


def generate(field: Field, catalog: Catalog, out_path: Path, *, seed: int) -> Path:
    image = render_field(field, catalog, seed=seed)
    return write_fits_image(out_path, image, extra_header=wcs_header_cards(field))


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a synthetic FITS star field."
    )
    parser.add_argument("--ra", type=float, default=Field.ra_center_deg)
    parser.add_argument("--dec", type=float, default=Field.dec_center_deg)
    parser.add_argument("--mag-limit", type=float, default=Field.mag_limit)
    parser.add_argument("--max-stars", type=int, default=Field.max_stars)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--tycho-dir", type=Path, default=Path("tycho2"))
    parser.add_argument("--hyg", type=Path, default=Path("hyg4.2/hygdata_v42.csv"))
    parser.add_argument("--cache", type=Path, default=Path("testdata/starfield.npz"))
    parser.add_argument(
        "--out", type=Path, default=Path("synthetic_qhy5iii462_starfield.fits")
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    field = Field(
        ra_center_deg=args.ra,
        dec_center_deg=args.dec,
        mag_limit=args.mag_limit,
        max_stars=args.max_stars,
    )
    print(
        f"Field centre RA={field.ra_center_deg} deg, Dec={field.dec_center_deg} deg, "
        f"FOV={field.fov_x_deg:.2f} x {field.fov_y_deg:.2f} deg, "
        f"scale={field.pixel_scale_arcsec:.3f} arcsec/px, mag < {field.mag_limit}"
    )
    try:
        catalog, source = load_catalog(
            field, tycho_dir=args.tycho_dir, hyg_path=args.hyg, cache_path=args.cache
        )
    except NoCatalogError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"Loaded {len(catalog)} stars from {source}")
    if len(catalog) == 0:
        print("No stars in field; try a larger FOV or fainter magnitude limit.")
        return 1

    out_path = generate(field, catalog, args.out, seed=args.seed)
    print(f"Wrote {out_path} with {len(catalog)} stars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
