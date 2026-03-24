from dataclasses import dataclass
import datetime


@dataclass
class PolarResult:
    alt_correction_arcsec: float | None
    az_correction_arcsec: float | None
    residual_arcsec: float | None
    confidence: float | None
    message: str | None = None


@dataclass
class _PoseObservation:
    """Result of a single capture→solve at one RA position."""

    ra_rad: float
    dec_rad: float
    rms_arcsec: float
    timestamp_utc: datetime.datetime


@dataclass
class _CircleFitResult:
    """Result of fitting a small circle to three or more pose observations."""

    pole_ra_rad: float
    pole_dec_rad: float
    radius_rad: float
    residual_rad: float
