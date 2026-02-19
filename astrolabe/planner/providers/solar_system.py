from .base import CatalogProvider
from astrolabe.errors import NotImplementedFeature


class SolarSystemProvider(CatalogProvider):
    name = "solar_system"

    def list_targets(self):
        raise NotImplementedFeature("Solar system catalog not implemented")
