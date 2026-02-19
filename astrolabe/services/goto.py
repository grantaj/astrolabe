from dataclasses import dataclass
from astrolabe.errors import NotImplementedFeature


@dataclass
class GotoResult:
    success: bool
    final_error_arcsec: float | None
    iterations: int
    message: str | None = None


class GotoService:
    def __init__(self, mount_backend, camera_backend, solver_backend):
        self._mount = mount_backend
        self._camera = camera_backend
        self._solver = solver_backend

    def center_target(
        self,
        target_ra_rad: float,
        target_dec_rad: float,
        tolerance_arcsec: float,
        max_iterations: int,
    ) -> GotoResult:
        raise NotImplementedFeature("Goto centering not implemented")
