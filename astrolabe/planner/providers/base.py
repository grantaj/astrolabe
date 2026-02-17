from abc import ABC, abstractmethod


class CatalogProvider(ABC):
    name: str

    @abstractmethod
    def list_targets(self):
        pass
