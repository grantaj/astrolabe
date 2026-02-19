from .base import CatalogProvider
from .catalog import LocalCuratedCatalogProvider
from .solar_system import SolarSystemProvider


def get_catalog_providers():
    return [
        LocalCuratedCatalogProvider(),
    ]

__all__ = [
    "CatalogProvider",
    "LocalCuratedCatalogProvider",
    "SolarSystemProvider",
    "get_catalog_providers",
]
