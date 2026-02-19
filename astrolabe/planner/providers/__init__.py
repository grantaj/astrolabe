from .base import CatalogProvider
from .catalog import LocalCuratedCatalogProvider
from .solar_system import SolarSystemProvider, list_solar_system_targets


def get_catalog_providers():
    return [
        LocalCuratedCatalogProvider(),
    ]

__all__ = [
    "CatalogProvider",
    "LocalCuratedCatalogProvider",
    "SolarSystemProvider",
    "list_solar_system_targets",
    "get_catalog_providers",
]
