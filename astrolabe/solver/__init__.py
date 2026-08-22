from .astap import AstapSolverBackend
from .tetra3 import Tetra3SolverBackend
from .types import SolveRequest, SolveResult
from .base import SolverBackend


def get_solver_backend(config) -> SolverBackend:
    solver_name = getattr(config, "solver_name", None) or "astap"
    if solver_name == "astap":
        return AstapSolverBackend(
            binary=config.solver_binary, database_path=config.solver_database_path
        )
    if solver_name == "tetra3":
        if not config.solver_database_path:
            raise ValueError(
                "tetra3 requires an explicit [solver].database_path: a tetra3 .npz "
                "database, or 'default_database' for tetra3's bundled 10-30 deg one"
            )
        return Tetra3SolverBackend(
            database_path=config.solver_database_path,
            fallback_fov_deg=config.solver_fov_deg,
            fov_tolerance_deg=config.solver_fov_tolerance_deg,
        )
    raise ValueError(f"Unknown solver backend: {solver_name}")
