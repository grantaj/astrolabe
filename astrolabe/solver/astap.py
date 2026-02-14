import subprocess
import re
import math
from pathlib import Path
from typing import Optional
from .types import SolveRequest, SolveResult
from .base import SolverBackend
import tempfile
import os

DEFAULT_ASTAP_TIMEOUT_S = 60


def _summarize_astap_failure(stdout: str, stderr: str) -> str:
    text = stdout.strip() or stderr.strip()
    if not text:
        return "Unknown error"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    priority = [
        "Only 0 stars found",
        "No solution found",
        "Old database",
        "not enough stars",
        "Error",
    ]
    for p in priority:
        for line in lines:
            if p in line:
                return line
    return lines[-1]


class AstapSolverBackend(SolverBackend):
    def __init__(self, binary: str = "astap_cli", database_path: Optional[str] = None):
        self.binary = binary
        self.database_path = database_path

    def solve(self, request: SolveRequest) -> SolveResult:
        fits_path = request.image.data if isinstance(request.image.data, (str, Path)) else None
        if not fits_path:
            return SolveResult(success=False, ra_rad=None, dec_rad=None, pixel_scale_arcsec=None,
                               rotation_rad=None, rms_arcsec=None, num_stars=None,
                               message="Image data must be a file path for ASTAP backend.")

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "astap_result"
            cmd = [self.binary, "-f", str(fits_path), "-r", "-o", str(base)]
            if self.database_path:
                cmd += ["-d", self.database_path]
            if request.ra_hint_rad is not None and request.dec_hint_rad is not None:
                ra_rad = request.ra_hint_rad % (2.0 * math.pi)
                ra_hours = math.degrees(ra_rad) / 15.0
                dec_deg = math.degrees(request.dec_hint_rad)
                spd_deg = 90.0 - dec_deg
                cmd += ["-ra", str(ra_hours), "-spd", str(spd_deg)]
            if request.scale_hint_arcsec is not None:
                cmd += ["-scale", str(request.scale_hint_arcsec)]
            if request.search_radius_rad is not None:
                radius_deg = math.degrees(request.search_radius_rad)
                cmd += ["-radius", str(radius_deg)]
            if request.extra_options:
                for k, v in request.extra_options.items():
                    cmd += [f"--{k}", str(v)]

            try:
                timeout_s = request.timeout_s if request.timeout_s is not None else DEFAULT_ASTAP_TIMEOUT_S
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
                if result.returncode != 0:
                    reason = _summarize_astap_failure(result.stdout, result.stderr)
                    raw_output = (result.stdout or "").strip() or (result.stderr or "").strip() or None
                    return SolveResult(success=False, ra_rad=None, dec_rad=None, pixel_scale_arcsec=None,
                                       rotation_rad=None, rms_arcsec=None, num_stars=None,
                                       message=f"ASTAP failed: {reason}", raw_output=raw_output)
                ini_path = str(base) + ".ini"
                if not os.path.exists(ini_path):
                    return SolveResult(success=False, ra_rad=None, dec_rad=None, pixel_scale_arcsec=None,
                                       rotation_rad=None, rms_arcsec=None, num_stars=None,
                                       message="ASTAP did not produce .ini file.")
                # Parse .ini file
                ra_rad = dec_rad = pixel_scale_arcsec = rotation_rad = rms_arcsec = num_stars = None
                scale1 = scale2 = None
                with open(ini_path, "r") as f:
                    for line in f:
                        if line.startswith("CRVAL1="):
                            ra_deg = float(line.split("=")[1])
                            ra_rad = math.radians(ra_deg)
                        elif line.startswith("CRVAL2="):
                            dec_deg = float(line.split("=")[1])
                            dec_rad = math.radians(dec_deg)
                        elif line.startswith("CDELT1="):
                            scale1 = abs(float(line.split("=")[1])) * 3600
                        elif line.startswith("CDELT2="):
                            scale2 = abs(float(line.split("=")[1])) * 3600
                        elif line.startswith("CROTA1="):
                            rotation_rad = math.radians(float(line.split("=")[1]))
                        elif line.startswith("PLTSOLVD=") and "T" in line:
                            pass  # solved
                        elif line.startswith("WARNING="):
                            pass  # can add to message
                        elif line.startswith("CMDLINE="):
                            pass  # can add to message
                if scale1 is not None and scale2 is not None:
                    pixel_scale_arcsec = (scale1 + scale2) / 2

                if ra_rad is None or dec_rad is None:
                    return SolveResult(
                        success=False,
                        ra_rad=None,
                        dec_rad=None,
                        pixel_scale_arcsec=pixel_scale_arcsec,
                        rotation_rad=rotation_rad,
                        rms_arcsec=rms_arcsec,
                        num_stars=num_stars,
                        message="ASTAP .ini missing CRVAL1/CRVAL2.",
                    )
                # Optionally parse .wcs or .ini for RMS and num_stars
                wcs_path = str(base) + ".wcs"
                if os.path.exists(wcs_path):
                    with open(wcs_path, "r") as wf:
                        for line in wf:
                            if "Offset was" in line:
                                m = re.search(r"Offset was ([\d.]+)\"", line)
                                if m:
                                    rms_arcsec = float(m.group(1))
                            if "stars" in line:
                                m = re.search(r"(\d+) stars", line)
                                if m:
                                    num_stars = int(m.group(1))
                # If num_stars not found in .wcs, parse from stdout
                if num_stars is None and result.stdout:
                    m = re.search(r"(\d+) stars,", result.stdout)
                    if m:
                        num_stars = int(m.group(1))
                # Clean up temp files (handled by TemporaryDirectory)
                return SolveResult(
                    success=True,
                    ra_rad=ra_rad,
                    dec_rad=dec_rad,
                    pixel_scale_arcsec=pixel_scale_arcsec,
                    rotation_rad=rotation_rad,
                    rms_arcsec=rms_arcsec,
                    num_stars=num_stars,
                    message="ASTAP solve succeeded (.ini/.wcs parsed)"
                )
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
