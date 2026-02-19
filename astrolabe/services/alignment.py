from dataclasses import dataclass
from astrolabe.solver.types import SolveResult
from astrolabe.errors import NotImplementedFeature


@dataclass
class AlignmentResult:
    success: bool
    solves_attempted: int
    solves_succeeded: int
    rms_arcsec: float | None
    message: str | None = None


class AlignmentService:
    def __init__(self, mount_backend, camera_backend, solver_backend):
        self._mount = mount_backend
        self._camera = camera_backend
        self._solver = solver_backend

    def solve_current(self, exposure_s: float | None = None) -> SolveResult:
        raise NotImplementedFeature("Alignment solve-current not implemented")

    def sync_current(self, exposure_s: float | None = None) -> AlignmentResult:
        raise NotImplementedFeature("Alignment sync not implemented")

    def initial_alignment(
        self,
        target_count: int,
        exposure_s: float | None = None,
        max_attempts: int | None = None,
    ) -> AlignmentResult:
        raise NotImplementedFeature("Initial alignment not implemented")
