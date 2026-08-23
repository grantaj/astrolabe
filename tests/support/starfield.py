"""Deterministic synthetic star fields with a known WCS.

Stars come from the catalogue embedded in a tetra3 database, so no catalogue
download or network access is required. The output is a 2D 16-bit image and a
standard TAN WCS (`CDELT1 < 0`, `CROTA2 = rotation`).

Used by `tests/solver/test_tetra3.py` and `scripts/benchmark_solvers.py`.
"""

from __future__ import annotations

import math

import numpy as np


def catalog_from_tetra3(solver) -> np.ndarray:
    """Return an (N, 3) array of (ra_rad, dec_rad, magnitude) from a tetra3 database."""
    table = np.asarray(solver.star_table, dtype=np.float64)
    return table[:, [0, 1, 5]]


def _cd_matrix(scale_deg: float, rotation_deg: float) -> np.ndarray:
    rot = math.radians(rotation_deg)
    cdelt1, cdelt2 = -scale_deg, scale_deg
    return np.array(
        [
            [cdelt1 * math.cos(rot), -cdelt2 * math.sin(rot)],
            [cdelt1 * math.sin(rot), cdelt2 * math.cos(rot)],
        ]
    )


def _gnomonic(ra: np.ndarray, dec: np.ndarray, ra0: float, dec0: float):
    d_ra = ra - ra0
    cos_c = np.sin(dec0) * np.sin(dec) + np.cos(dec0) * np.cos(dec) * np.cos(d_ra)
    xi = np.cos(dec) * np.sin(d_ra) / cos_c
    eta = (
        np.cos(dec0) * np.sin(dec) - np.sin(dec0) * np.cos(dec) * np.cos(d_ra)
    ) / cos_c
    return np.degrees(xi), np.degrees(eta), cos_c


def render_field(
    catalog: np.ndarray,
    ra_deg: float,
    dec_deg: float,
    fov_deg: float,
    width: int,
    height: int,
    rotation_deg: float = 0.0,
    noise_sigma: float = 0.0,
    seed: int = 20240101,
) -> tuple[np.ndarray, dict[str, float | str]]:
    """Render stars through a TAN WCS and return (uint16 image, WCS header values).

    The returned array is in FITS storage order: row 0 is the bottom of the image
    (increasing FITS ``y``).
    """
    scale_deg = fov_deg / width
    cd = _cd_matrix(scale_deg, rotation_deg)
    cd_inv = np.linalg.inv(cd)
    crpix1, crpix2 = (width + 1) / 2.0, (height + 1) / 2.0
    ra0, dec0 = math.radians(ra_deg), math.radians(dec_deg)

    xi, eta, cos_c = _gnomonic(catalog[:, 0], catalog[:, 1], ra0, dec0)
    offsets = cd_inv @ np.vstack([xi, eta])
    x = offsets[0] + crpix1
    y = offsets[1] + crpix2

    margin = 4
    visible = (
        (cos_c > 0)
        & (x >= margin)
        & (x < width - margin)
        & (y >= margin)
        & (y < height - margin)
    )

    rng = np.random.default_rng(seed)
    background, sigma_px, peak = 500.0, 1.5, 45000.0
    image = np.full((height, width), background, dtype=np.float64)
    span = np.arange(-4, 5)
    for xi_px, yi_px, mag in zip(x[visible], y[visible], catalog[visible, 2]):
        col, row = int(round(xi_px - 1)), int(round(yi_px - 1))
        flux = peak * 10 ** (-0.4 * (mag + 1.5)) * 20.0
        cols = col + span
        rows = row + span
        inside_c = (cols >= 0) & (cols < width)
        inside_r = (rows >= 0) & (rows < height)
        dx = (cols[inside_c] - (xi_px - 1)) ** 2
        dy = (rows[inside_r] - (yi_px - 1)) ** 2
        psf = np.exp(-(dy[:, None] + dx[None, :]) / (2 * sigma_px**2))
        image[np.ix_(rows[inside_r], cols[inside_c])] += flux * psf

    if noise_sigma > 0:
        image += rng.normal(0.0, noise_sigma, image.shape)

    pixels = np.clip(image, 0, 65535).astype(np.uint16)
    header = {
        "CRPIX1": crpix1,
        "CRPIX2": crpix2,
        "CRVAL1": ra_deg,
        "CRVAL2": dec_deg,
        "CDELT1": -scale_deg,
        "CDELT2": scale_deg,
        "CROTA1": rotation_deg,
        "CROTA2": rotation_deg,
        "CTYPE1": "RA---TAN",
        "CTYPE2": "DEC--TAN",
    }
    return pixels, header
