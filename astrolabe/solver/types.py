from dataclasses import dataclass
from typing import Optional, Dict, Any

# Compatibility alias for callers that previously imported Image from solver.types.
# The captured-frame contract is owned by astrolabe.camera.
from astrolabe.camera.types import Image


@dataclass
class SolveRequest:
    image: Image
    ra_hint_rad: Optional[float] = None
    dec_hint_rad: Optional[float] = None
    scale_hint_arcsec: Optional[float] = None
    parity_hint: Optional[int] = None
    search_radius_rad: Optional[float] = None
    timeout_s: Optional[float] = None
    extra_options: Optional[Dict[str, Any]] = None


@dataclass
class SolveResult:
    success: bool
    ra_rad: Optional[float]
    dec_rad: Optional[float]
    pixel_scale_arcsec: Optional[float]
    rotation_rad: Optional[float]
    rms_arcsec: Optional[float]
    num_stars: Optional[int]
    message: Optional[str] = None
    raw_output: Optional[str] = None
