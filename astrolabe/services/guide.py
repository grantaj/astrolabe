from dataclasses import dataclass
from astrolabe.errors import NotImplementedFeature


@dataclass
class CalibrationResult:
    success: bool
    message: str | None = None


@dataclass
class GuidingStatus:
    running: bool
    rms_arcsec: float | None
    star_lost: bool
    last_error_arcsec: float | None


class GuidingService:
    def __init__(self, mount_backend, camera_backend):
        self._mount = mount_backend
        self._camera = camera_backend

    def calibrate(self, duration_s: float) -> CalibrationResult:
        raise NotImplementedFeature("Guiding calibration not implemented")

    def start(self, aggression: float, min_move_arcsec: float) -> None:
        raise NotImplementedFeature("Guiding start not implemented")

    def stop(self) -> None:
        raise NotImplementedFeature("Guiding stop not implemented")

    def status(self) -> GuidingStatus:
        raise NotImplementedFeature("Guiding status not implemented")
