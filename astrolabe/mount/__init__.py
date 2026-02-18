from .base import MountBackend, MountState
from .indi import IndiMountBackend


def get_mount_backend(config):
    backend = config.mount_backend
    if backend == "indi":
        return IndiMountBackend(config)
    raise ValueError(f"Unsupported mount backend: {backend}")

__all__ = ["MountBackend", "MountState", "IndiMountBackend", "get_mount_backend"]
