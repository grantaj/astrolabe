import subprocess
import re
from pathlib import Path
from typing import Optional
from .types import SolveRequest, SolveResult
from .base import SolverBackend
import tempfile
import os

from astrolabe.util.math import (
    degrees_to_rad,
    normalize_angle_rad,
    rad_to_degrees,
    rad_to_hours,
)

DEFAULT_ASTAP_TIMEOUT_S = 60
_FITS_BLOCK_BYTES = 2880
_FITS_CARD_BYTES = 80


def _fits_image_height_px(path: str | Path) -> int | None:
    """Return the primary FITS image height when it can be read cheaply."""

    try:
        with Path(path).open("rb") as handle:
            first_block = True
            while True:
                block = handle.read(_FITS_BLOCK_BYTES)
                if len(block) != _FITS_BLOCK_BYTES:
                    return None
                if first_block:
                    first_block = False
                    if not block.startswith(b"SIMPLE"):
                        return None
                for offset in range(0, _FITS_BLOCK_BYTES, _FITS_CARD_BYTES):
                    raw_card = block[offset : offset + _FITS_CARD_BYTES]
                    try:
                        card = raw_card.decode("ascii")
                    except UnicodeDecodeError:
                        return None
                    key = card[:8].strip()
                    if key == "END":
                        return None
                    if key != "NAXIS2" or card[8:10] != "= ":
                        continue
                    value = card[10:].split("/", 1)[0].strip()
                    try:
                        height_px = int(value)
                    except ValueError:
                        return None
                    return height_px if height_px > 0 else None
    except OSError:
        return None


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
        fits_path = (
            request.image.data if isinstance(request.image.data, (str, Path)) else None
        )
        if not fits_path:
            return SolveResult(
                success=False,
                ra_rad=None,
                dec_rad=None,
                pixel_scale_arcsec=None,
                rotation_rad=None,
                rms_arcsec=None,
                num_stars=None,
                message="Image data must be a file path for ASTAP backend.",
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "astap_result"
            cmd = [self.binary, "-f", str(fits_path), "-o", str(base)]
            if self.database_path:
                cmd += ["-d", self.database_path]
            if request.ra_hint_rad is not None and request.dec_hint_rad is not None:
                ra_rad = normalize_angle_rad(request.ra_hint_rad)
                ra_hours = rad_to_hours(ra_rad)
                dec_deg = rad_to_degrees(request.dec_hint_rad)
                spd_deg = 90.0 - dec_deg
                cmd += ["-ra", str(ra_hours), "-spd", str(spd_deg)]
            if request.scale_hint_arcsec is not None:
                height_px = request.image.height_px
                if height_px <= 0:
                    height_px = _fits_image_height_px(fits_path) or 0
                if height_px > 0:
                    fov_deg = request.scale_hint_arcsec * height_px / 3600.0
                    cmd += ["-fov", str(fov_deg)]
            if request.search_radius_rad is not None:
                radius_deg = rad_to_degrees(request.search_radius_rad)
                cmd += ["-r", str(radius_deg)]
            if request.extra_options:
                for k, v in request.extra_options.items():
                    cmd += [f"--{k}", str(v)]

            try:
                timeout_s = (
                    request.timeout_s
                    if request.timeout_s is not None
                    else DEFAULT_ASTAP_TIMEOUT_S
                )
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout_s
                )
                if result.returncode != 0:
                    reason = _summarize_astap_failure(result.stdout, result.stderr)
                    raw_output = (
                        (result.stdout or "").strip()
                        or (result.stderr or "").strip()
                        or None
                    )
                    return SolveResult(
                        success=False,
                        ra_rad=None,
                        dec_rad=None,
                        pixel_scale_arcsec=None,
                        rotation_rad=None,
                        rms_arcsec=None,
                        num_stars=None,
                        message=f"ASTAP failed: {reason}",
                        raw_output=raw_output,
                    )
                ini_path = str(base) + ".ini"
                if not os.path.exists(ini_path):
                    return SolveResult(
                        success=False,
                        ra_rad=None,
                        dec_rad=None,
                        pixel_scale_arcsec=None,
                        rotation_rad=None,
                        rms_arcsec=None,
                        num_stars=None,
                        message="ASTAP did not produce .ini file.",
                    )
                # Parse .ini file
                ra_rad = dec_rad = pixel_scale_arcsec = rotation_rad = rms_arcsec = (
                    num_stars
                ) = None
                scale1 = scale2 = None
                with open(ini_path, "r") as f:
                    for line in f:
                        if line.startswith("CRVAL1="):
                            ra_deg = float(line.split("=")[1])
                            ra_rad = degrees_to_rad(ra_deg)
                        elif line.startswith("CRVAL2="):
                            dec_deg = float(line.split("=")[1])
                            dec_rad = degrees_to_rad(dec_deg)
                        elif line.startswith("CDELT1="):
                            scale1 = abs(float(line.split("=")[1])) * 3600
                        elif line.startswith("CDELT2="):
                            scale2 = abs(float(line.split("=")[1])) * 3600
                        elif line.startswith("CROTA1="):
                            rotation_rad = degrees_to_rad(float(line.split("=")[1]))
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
                    message="ASTAP solve succeeded (.ini/.wcs parsed)",
                )
            except Exception as e:
                return SolveResult(
                    success=False,
                    ra_rad=None,
                    dec_rad=None,
                    pixel_scale_arcsec=None,
                    rotation_rad=None,
                    rms_arcsec=None,
                    num_stars=None,
                    message=f"Exception running ASTAP: {e}",
                )

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
