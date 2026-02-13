import subprocess
from pathlib import Path
from typing import Optional
from .types import SolveRequest, SolveResult
from .base import SolverBackend

class AstapSolverBackend(SolverBackend):
    def __init__(self, binary: str = "astap_cli"):
        self.binary = binary

    def solve(self, request: SolveRequest) -> SolveResult:
        # Assume request.image.data is a file path to the FITS file
        fits_path = request.image.data if isinstance(request.image.data, (str, Path)) else None
        if not fits_path:
            return SolveResult(success=False, ra_rad=None, dec_rad=None, pixel_scale_arcsec=None,
                               rotation_rad=None, rms_arcsec=None, num_stars=None,
                               message="Image data must be a file path for ASTAP backend.")

        cmd = [self.binary, "-f", str(fits_path), "-r"]
        # Add hints if available
        if request.ra_hint_rad is not None and request.dec_hint_rad is not None:
            cmd += ["-ra", str(request.ra_hint_rad), "-dec", str(request.dec_hint_rad)]
        if request.scale_hint_arcsec is not None:
            cmd += ["-scale", str(request.scale_hint_arcsec)]
        if request.search_radius_deg is not None:
            cmd += ["-radius", str(request.search_radius_deg)]
        # Add any extra options
        if request.extra_options:
            for k, v in request.extra_options.items():
                cmd += [f"--{k}", str(v)]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                return SolveResult(success=False, ra_rad=None, dec_rad=None, pixel_scale_arcsec=None,
                                   rotation_rad=None, rms_arcsec=None, num_stars=None,
                                   message=f"ASTAP failed: {result.stderr.strip()}")
            # Parse ASTAP output (placeholder: real parsing needed)
            # Example: parse stdout for RA, Dec, scale, rotation, RMS, num_stars
            # For now, just return success with dummy values
            return SolveResult(success=True, ra_rad=0.0, dec_rad=0.0, pixel_scale_arcsec=1.0,
                               rotation_rad=0.0, rms_arcsec=0.0, num_stars=10, message="ASTAP solve succeeded (parsing not implemented)")
        except Exception as e:
            return SolveResult(success=False, ra_rad=None, dec_rad=None, pixel_scale_arcsec=None,
                               rotation_rad=None, rms_arcsec=None, num_stars=None,
                               message=f"Exception running ASTAP: {e}")

    def is_available(self) -> dict:
        try:
            result = subprocess.run(
                [self.binary, "-h"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=3,
            )
            if result.returncode == 0:
                return {"ok": True, "detail": "responds to -h"}
            else:
                return {"ok": False, "detail": "returned non-zero"}
        except FileNotFoundError:
            return {"ok": False, "detail": "not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "detail": "timeout"}
