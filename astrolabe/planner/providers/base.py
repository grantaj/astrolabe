from abc import ABC, abstractmethod
from typing import Sequence

from astrolabe.planner.types import Target


class CatalogProvider(ABC):
    name: str

    @abstractmethod
    def list_targets(self) -> Sequence[Target]:
        raise NotImplementedError
