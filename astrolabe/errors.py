class AstrolabeError(Exception):
    """Base exception for Astrolabe errors."""


class BackendError(AstrolabeError):
    """Raised for backend failures or invalid backend state."""


class ServiceError(AstrolabeError):
    """Raised for service-layer failures."""


class NotImplementedFeature(NotImplementedError, AstrolabeError):
    """Raised for stubbed or unimplemented features."""
