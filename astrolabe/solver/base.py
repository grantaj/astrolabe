from abc import ABC, abstractmethod
from .types import SolveRequest, SolveResult


class SolverBackend(ABC):
    @abstractmethod
    def solve(self, request: SolveRequest) -> SolveResult:
        pass

    def is_available(self) -> dict:
        """Return a dict with 'ok' (bool) and 'detail' (str) for doctor checks."""
        return {"ok": False, "detail": "not implemented"}
