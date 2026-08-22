#!/usr/bin/env python3
"""Baseline ASTAP against tetra3 on identical deterministic synthetic fields.

Reports success, solve time, centre error, pixel-scale error, rotation error,
matched stars and RMS.

Fields are rendered from a tetra3 `.npz` star table. `--catalog` accepts a
database path, so ASTAP can be benchmarked without tetra3 installed; the bare
name `default_database` resolves inside an installed tetra3. Unavailable
backends are reported and skipped.

`--astap-binary` must point at a wrapper, not stock `astap_cli`:
`AstapSolverBackend` emits an invalid argv (`astap.py:62-78` passes `-r`
valueless, so `-o` is consumed as the radius; `-scale`/`-radius` are not
`astap_cli` flags). `is_available()` only probes `-h`, so a stock binary is
admitted and then every row fails. The recorded run wrapped `-D w08 -r 180`.

Usage:
  python scripts/benchmark_solvers.py --fov-deg 20 --astap-db ~/.astap \\
      --astap-binary ./astap_wrapper.sh
"""

from __future__ import annotations

import argparse
import datetime
import math
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from astrolabe.camera.pixels import write_fits_image
from astrolabe.camera.types import Image
from astrolabe.solver.astap import AstapSolverBackend
from astrolabe.solver.base import SolverBackend
from astrolabe.solver.tetra3 import Tetra3SolverBackend
from astrolabe.solver.types import SolveRequest
from astrolabe.util.math import angular_separation_rad, degrees_to_rad, rad_to_arcsec

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from support.starfield import render_field  # noqa: E402  # ty: ignore[unresolved-import]

FIELDS = [
    ("blind", 0.0, 0.0),
    ("rotated", 37.5, 0.0),
    ("noisy", 0.0, 40.0),
]

HEADER = (
    f"{'field':<9} {'backend':<8} {'ok':<5} {'time_s':>7} {'centre_err_as':>14} "
    f"{'scale_err_%':>12} {'rot_err_deg':>12} {'stars':>6} {'rms_as':>8}"
)


ASTAP_ARGV_NOTE = (
    "# note: AstapSolverBackend emits an invalid astap_cli argv; --astap-binary\n"
    "#       must be a wrapper. The recorded run appended `-D w08 -r 180`."
)

ASTAP_FAILURE_NOTE = (
    "# ASTAP rows failed: with a stock astap_cli this is the known argv defect,\n"
    "#       not a solving-quality result."
)


def _star_catalog(database: str) -> np.ndarray:
    """Return an (N, 3) array of (ra_rad, dec_rad, magnitude) from a tetra3 database."""
    path = Path(database).expanduser()
    if path.suffix != ".npz":
        import tetra3  # ty: ignore[unresolved-import]

        path = Path(tetra3.__file__).parent / "data" / f"{database}.npz"
    with np.load(path) as data:
        return np.asarray(data["star_table"], dtype=np.float64)[:, [0, 1, 5]]


def _measured(value: float | None, width: int, precision: int) -> str:
    """Render an optional metric, distinguishing a genuine value from an absent one."""
    if value is None:
        return f"{'n/a':>{width}}"
    return f"{value:>{width}.{precision}f}"


def _row(field: str, backend: str, result, elapsed: float, truth: dict) -> str:
    if not result.success:
        return f"{field:<9} {backend:<8} {'no':<5} {elapsed:>7.2f}  {result.message}"

    centre_err = (
        rad_to_arcsec(
            angular_separation_rad(
                result.ra_rad, result.dec_rad, truth["ra_rad"], truth["dec_rad"]
            )
        )
        if result.ra_rad is not None and result.dec_rad is not None
        else None
    )
    scale_err = (
        100.0 * (result.pixel_scale_arcsec / truth["scale_arcsec"] - 1.0)
        if result.pixel_scale_arcsec is not None
        else None
    )
    rot_err = (
        math.degrees(result.rotation_rad) - truth["rotation_deg"]
        if result.rotation_rad is not None
        else None
    )
    stars = f"{'n/a':>6}" if result.num_stars is None else f"{result.num_stars:>6}"
    return (
        f"{field:<9} {backend:<8} {'yes':<5} {elapsed:>7.2f} "
        f"{_measured(centre_err, 14, 2)} {_measured(scale_err, 12, 3)} "
        f"{_measured(rot_err, 12, 3)} {stars} {_measured(result.rms_arcsec, 8, 2)}"
    )


def _timed_solve(backend: SolverBackend, request: SolveRequest):
    started = time.perf_counter()
    result = backend.solve(request)
    return result, time.perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ra-deg", type=float, default=83.0)
    parser.add_argument("--dec-deg", type=float, default=-5.0)
    parser.add_argument("--fov-deg", type=float, default=20.0)
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=768)
    parser.add_argument(
        "--astap-binary",
        default="astap_cli",
        help=(
            "ASTAP binary. Must be a wrapper, not stock astap_cli, which cannot "
            "solve through AstapSolverBackend's invalid argv; the recorded run "
            "appended `-D w08 -r 180`."
        ),
    )
    parser.add_argument("--astap-db", default=None)
    parser.add_argument("--tetra3-db", default="default_database")
    parser.add_argument("--catalog", default=None)
    args = parser.parse_args()

    candidates: dict[str, SolverBackend] = {
        "astap": AstapSolverBackend(
            binary=args.astap_binary, database_path=args.astap_db
        ),
        "tetra3": Tetra3SolverBackend(
            database_path=args.tetra3_db, fallback_fov_deg=args.fov_deg
        ),
    }
    backends = {}
    for name, backend in candidates.items():
        available = backend.is_available()
        print(f"# {name}: ok={available['ok']} {available['detail']}")
        if available["ok"]:
            backends[name] = backend
    if not backends:
        print("# no solver backend is available; nothing to benchmark")
        return
    if "astap" in backends:
        print(ASTAP_ARGV_NOTE)

    catalog = _star_catalog(args.tetra3_db if args.catalog is None else args.catalog)
    scale_arcsec = args.fov_deg * 3600 / args.width
    print(HEADER)

    astap_failed = False

    with tempfile.TemporaryDirectory() as tmpdir:
        for field, rotation_deg, noise_sigma in FIELDS:
            pixels, header = render_field(
                catalog,
                ra_deg=args.ra_deg,
                dec_deg=args.dec_deg,
                fov_deg=args.fov_deg,
                width=args.width,
                height=args.height,
                rotation_deg=rotation_deg,
                noise_sigma=noise_sigma,
            )
            path = Path(tmpdir) / f"{field}.fits"
            write_fits_image(path, pixels, extra_header=header)
            image = Image(
                data=str(path),
                width_px=args.width,
                height_px=args.height,
                timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
                exposure_s=2.0,
                metadata={},
            )
            truth = {
                "ra_rad": degrees_to_rad(args.ra_deg),
                "dec_rad": degrees_to_rad(args.dec_deg),
                "scale_arcsec": scale_arcsec,
                "rotation_deg": rotation_deg,
            }
            request = SolveRequest(image=image, scale_hint_arcsec=scale_arcsec)
            for name, backend in backends.items():
                result, elapsed = _timed_solve(backend, request)
                astap_failed = astap_failed or (name == "astap" and not result.success)
                print(_row(field, name, result, elapsed, truth))

    if astap_failed:
        print(ASTAP_FAILURE_NOTE)


if __name__ == "__main__":
    main()
