from .base import CatalogProvider
from astrolabe.errors import NotImplementedFeature


class MessierProvider(CatalogProvider):
    name = "messier"

    def list_targets(self):
        raise NotImplementedFeature("Messier catalog not implemented")
