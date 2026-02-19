from dataclasses import dataclass
from astrolabe.errors import NotImplementedFeature


@dataclass
class PolarResult:
    alt_correction_arcsec: float | None
    az_correction_arcsec: float | None
    residual_arcsec: float | None
    confidence: float | None
    message: str | None = None


class PolarAlignService:
    def __init__(self, mount_backend, camera_backend, solver_backend):
        self._mount = mount_backend
        self._camera = camera_backend
        self._solver = solver_backend

    def run(self, ra_rotation_rad: float) -> PolarResult:
        raise NotImplementedFeature("Polar alignment not implemented")
