from .base import CatalogProvider
from astrolabe.errors import NotImplementedFeature


class SouthernHighlightsProvider(CatalogProvider):
    name = "southern_highlights"

    def list_targets(self):
        raise NotImplementedFeature("Southern highlights catalog not implemented")
