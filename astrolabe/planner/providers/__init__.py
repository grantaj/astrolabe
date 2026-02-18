from .base import CatalogProvider
from .messier import MessierProvider
from .solar_system import SolarSystemProvider
from .southern_highlights import SouthernHighlightsProvider


def get_catalog_providers():
    return [
        MessierProvider(),
        SouthernHighlightsProvider(),
        SolarSystemProvider(),
    ]

__all__ = [
    "CatalogProvider",
    "MessierProvider",
    "SouthernHighlightsProvider",
    "SolarSystemProvider",
    "get_catalog_providers",
]
