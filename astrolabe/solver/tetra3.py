"""tetra3 plate-solving backend.

The backend contract, configuration keys and hint semantics live in
`docs/interfaces.md`; this module implements them. tetra3 is imported lazily so
that ASTAP-only installs are unaffected.
"""

from __future__ import annotations

import importlib
import json
import math
from pathlib import Path
from typing import Any, Optional

import numpy as np

from astrolabe.camera.pixels import image_to_pixels
from astrolabe.util.math import degrees_to_rad, rad_to_arcsec, rad_to_degrees

from .base import SolverBackend
from .types import SolveRequest, SolveResult

DEFAULT_TETRA3_FOV_TOLERANCE_DEG = 1.0

INSTALL_HINT = "install the optional extra with: uv sync --extra tetra3"

NUMPY_HINT = (
    "the pinned tetra3 release calls the `np.math` alias that NumPy 2.0 removed "
    "(upstream esa/tetra3 issue: np.math.factorial in tetra3.py), so it needs "
    f"NumPy < 2 at runtime; NumPy {np.__version__} is installed"
)


def _failure(message: str, raw_output: Optional[str] = None) -> SolveResult:
    return SolveResult(
        success=False,
        ra_rad=None,
        dec_rad=None,
        pixel_scale_arcsec=None,
        rotation_rad=None,
        rms_arcsec=None,
        num_stars=None,
        message=message,
        raw_output=raw_output,
    )


def rotation_rad_from_roll_deg(roll_deg: float) -> float:
    """Convert a tetra3 roll (degrees) to the Astrolabe/FITS CROTA rotation.

    tetra3 measures roll in its own top-left-origin, y-down pixel frame, while
    Astrolabe supplies FITS pixel data in FITS storage order (row 0 is the
    bottom row). That vertical flip negates the angle and offsets it by a half
    turn, so a tetra3 roll ``r`` in ``[0, 360)`` is CROTA ``180 - r`` in
    ``(-180, 180]``.
    """
    return degrees_to_rad(180.0 - (roll_deg % 360.0))


def pixel_scale_arcsec_from_fov(fov_deg: float, width_px: int) -> float:
    """Convert a true angular horizontal FOV to tangent-plane arcsec/pixel.

    The frame spans ``2 * tan(fov / 2)`` across ``width_px`` pixels on the
    tangent plane, so the per-pixel step is a ``CDELT``-style tangent-plane
    increment rather than an angle; scaling it with ``rad_to_arcsec`` is the
    same small-angle identification FITS ``CDELT`` makes, and is intentional.
    """
    return rad_to_arcsec(2.0 * math.tan(degrees_to_rad(fov_deg) / 2.0) / width_px)


def fov_estimate_deg(pixel_scale_arcsec: float, width_px: int) -> float:
    """Invert `pixel_scale_arcsec_from_fov`: tangent-plane scale to true FOV."""
    tangent_span = width_px * degrees_to_rad(pixel_scale_arcsec / 3600.0)
    return rad_to_degrees(2.0 * math.atan(tangent_span / 2.0))


def _numeric(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    return None


class Tetra3SolverBackend(SolverBackend):
    """Solve frames in-process with tetra3, loading its database once per instance."""

    def __init__(
        self,
        database_path: str,
        fallback_fov_deg: Optional[float] = None,
        fov_tolerance_deg: Optional[float] = None,
    ):
        self.database_path = str(Path(database_path).expanduser())
        self.fallback_fov_deg = fallback_fov_deg
        self.fov_tolerance_deg = (
            DEFAULT_TETRA3_FOV_TOLERANCE_DEG
            if fov_tolerance_deg is None
            else fov_tolerance_deg
        )
        self._module: Any = None
        self._solver: Any = None
        self._load_error: Optional[str] = None

    def _load(self) -> None:
        # A load failure is cached for the life of the instance: a CLI process
        # will not gain a working tetra3 install part-way through a run.
        if self._solver is not None or self._load_error is not None:
            return
        try:
            module = importlib.import_module("tetra3")
        except Exception as exc:
            self._load_error = f"tetra3 is not importable ({exc}); {INSTALL_HINT}"
            return
        # tetra3 calls `np.math` on the NumPy it imported; probing that module
        # keeps the diagnostic accurate if upstream ever stops doing so.
        if getattr(module, "np", None) is np and not hasattr(np, "math"):
            self._load_error = f"tetra3 cannot run here: {NUMPY_HINT}"
            return
        try:
            solver = module.Tetra3(load_database=self.database_path)
        except Exception as exc:
            self._load_error = (
                f"tetra3 database {self.database_path!r} could not be loaded: {exc}"
            )
            return
        if not solver.has_database:
            self._load_error = (
                f"tetra3 database {self.database_path!r} loaded no star patterns; "
                "generate one with Tetra3.generate_database for your FOV range"
            )
            return
        self._module = module
        self._solver = solver

    def _fov_estimate_deg(
        self, request: SolveRequest, width_px: int
    ) -> tuple[Optional[float], str]:
        scale = request.scale_hint_arcsec
        if scale:
            return fov_estimate_deg(scale, width_px), "scale hint"
        if self.fallback_fov_deg:
            return self.fallback_fov_deg, "configured fallback"
        return None, "no scale_hint_arcsec and no [solver].fov_deg fallback"

    def _fov_incompatibility(self, fov_deg: float) -> Optional[str]:
        props = self._solver.database_properties or {}
        min_fov = props.get("min_fov")
        max_fov = props.get("max_fov")
        if min_fov is None or max_fov is None:
            return None
        tolerance = self.fov_tolerance_deg
        if float(min_fov) - tolerance <= fov_deg <= float(max_fov) + tolerance:
            return None
        return (
            f"requested FOV {fov_deg:.3f} deg is outside the tetra3 database range "
            f"{float(min_fov):.3f}-{float(max_fov):.3f} deg "
            f"(tolerance {tolerance:.3f} deg); generate a database for this FOV"
        )

    def solve(self, request: SolveRequest) -> SolveResult:
        self._load()
        if self._solver is None:
            return _failure(str(self._load_error))

        try:
            pixels = np.asarray(image_to_pixels(request.image).pixels)
        except Exception as exc:
            return _failure(f"tetra3 could not decode the image payload: {exc}")
        if pixels.ndim != 2:
            return _failure(
                f"tetra3 requires a 2D monochrome frame, got shape {pixels.shape}"
            )
        width_px = pixels.shape[1]

        fov_deg, fov_source = self._fov_estimate_deg(request, width_px)
        if fov_deg is None:
            return _failure(f"tetra3 needs a field-of-view estimate: {fov_source}")

        incompatible = self._fov_incompatibility(fov_deg)
        if incompatible is not None:
            return _failure(f"tetra3 database/FOV mismatch: {incompatible}")

        timeout_ms = (
            request.timeout_s * 1000.0 if request.timeout_s is not None else None
        )
        try:
            centroids = self._module.get_centroids_from_image(pixels)
            solution = self._solver.solve_from_centroids(
                centroids,
                pixels.shape,
                fov_estimate=fov_deg,
                fov_max_error=self.fov_tolerance_deg,
                solve_timeout=timeout_ms,
            )
        except Exception as exc:
            return _failure(f"tetra3 raised {type(exc).__name__}: {exc}")

        return self._to_result(solution, width_px, fov_deg, fov_source)

    def _to_result(
        self,
        solution: dict,
        width_px: int,
        fov_deg: float,
        fov_source: str,
    ) -> SolveResult:
        numbers = {key: _numeric(value) for key, value in solution.items()}
        raw_output = json.dumps(
            {
                key: value if isinstance(value, str) else numbers[key]
                for key, value in solution.items()
                if isinstance(value, str) or numbers[key] is not None
            },
            sort_keys=True,
        )
        ra_deg = numbers.get("RA")
        dec_deg = numbers.get("Dec")
        if ra_deg is None or dec_deg is None:
            return _failure(
                f"tetra3 found no match at FOV {fov_deg:.3f} deg ({fov_source})",
                raw_output=raw_output,
            )

        solved_fov = numbers.get("FOV")
        rms = numbers.get("RMSE")
        matches = numbers.get("Matches")
        roll = numbers.get("Roll")
        prob = numbers.get("Prob")
        reported_fov = (
            f"{solved_fov:.4f} deg" if solved_fov is not None else "not reported"
        )
        reported_prob = f"{prob:.2e}" if prob is not None else "not reported"
        return SolveResult(
            success=True,
            ra_rad=degrees_to_rad(ra_deg),
            dec_rad=degrees_to_rad(dec_deg),
            pixel_scale_arcsec=(
                pixel_scale_arcsec_from_fov(solved_fov, width_px)
                if solved_fov is not None
                else None
            ),
            rotation_rad=(
                rotation_rad_from_roll_deg(roll) if roll is not None else None
            ),
            rms_arcsec=rms,
            num_stars=int(matches) if matches is not None else None,
            message=(
                "tetra3 solve succeeded "
                f"(matches={'not reported' if matches is None else int(matches)}, "
                f"fov={reported_fov}, false-positive probability={reported_prob})"
            ),
            raw_output=raw_output,
        )

    def is_available(self) -> dict:
        self._load()
        if self._solver is None:
            return {"ok": False, "detail": str(self._load_error)}
        props = self._solver.database_properties or {}
        return {
            "ok": True,
            "detail": (
                f"database {self.database_path} loaded "
                f"(FOV {float(props.get('min_fov', float('nan'))):.2f}"
                f"-{float(props.get('max_fov', float('nan'))):.2f} deg)"
            ),
        }
