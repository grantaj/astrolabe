from .astap import AstapSolverBackend
from .types import SolveRequest, SolveResult
from .base import SolverBackend


def get_solver_backend(config) -> SolverBackend:
    # For now, only ASTAP is supported, but this is extensible
    solver_name = getattr(config, "solver_name", None) or "astap"
    if solver_name == "astap":
        return AstapSolverBackend(
            binary=config.solver_binary, database_path=config.solver_database_path
        )
    # Future: add other backends here
    raise ValueError(f"Unknown solver backend: {solver_name}")
