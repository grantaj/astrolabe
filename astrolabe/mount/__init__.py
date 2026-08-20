from .base import MountBackend, MountState
from .indi import IndiMountBackend


def get_mount_backend(config) -> MountBackend:
    backend = config.mount_backend
    if backend == "indi":
        return IndiMountBackend(
            host=config.indi_host,
            port=config.indi_port,
            device=config.mount_device,
        )
    raise ValueError(f"Unsupported mount backend: {backend}")


__all__ = ["MountBackend", "MountState", "IndiMountBackend", "get_mount_backend"]
