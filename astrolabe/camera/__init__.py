from .indi import IndiCameraBackend
from .base import CameraBackend


def get_camera_backend(config) -> CameraBackend:
    backend = getattr(config, "camera_backend", None) or "indi"
    if backend == "indi":
        return IndiCameraBackend(
            host=config.indi_host,
            port=config.indi_port,
            device=config.camera_device,
            output_dir=config.camera_output_dir,
            output_prefix=config.camera_output_prefix,
            use_guider_exposure=config.camera_use_guider_exposure,
        )
    raise ValueError(f"Unknown camera backend: {backend}")


__all__ = ["CameraBackend", "IndiCameraBackend", "get_camera_backend"]
