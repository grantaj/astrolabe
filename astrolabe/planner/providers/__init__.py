from .base import CatalogProvider
from .catalog import LocalCuratedCatalogProvider
from .messier import MessierProvider
from .solar_system import SolarSystemProvider
from .southern_highlights import SouthernHighlightsProvider


def get_catalog_providers():
    return [
        LocalCuratedCatalogProvider(),
    ]

__all__ = [
    "CatalogProvider",
    "LocalCuratedCatalogProvider",
    "MessierProvider",
    "SouthernHighlightsProvider",
    "SolarSystemProvider",
    "get_catalog_providers",
]
