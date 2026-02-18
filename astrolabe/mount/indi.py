from .base import MountBackend, MountState
from astrolabe.errors import NotImplementedFeature


class IndiMountBackend(MountBackend):
    def __init__(self, config):
        self._config = config

    def connect(self) -> None:
        raise NotImplementedFeature("INDI mount backend not implemented")

    def disconnect(self) -> None:
        raise NotImplementedFeature("INDI mount backend not implemented")

    def is_connected(self) -> bool:
        raise NotImplementedFeature("INDI mount backend not implemented")

    def get_state(self) -> MountState:
        raise NotImplementedFeature("INDI mount backend not implemented")

    def slew_to(self, ra_rad: float, dec_rad: float) -> None:
        raise NotImplementedFeature("INDI mount backend not implemented")

    def sync(self, ra_rad: float, dec_rad: float) -> None:
        raise NotImplementedFeature("INDI mount backend not implemented")

    def stop(self) -> None:
        raise NotImplementedFeature("INDI mount backend not implemented")

    def park(self) -> None:
        raise NotImplementedFeature("INDI mount backend not implemented")

    def pulse_guide(self, ra_ms: float, dec_ms: float) -> None:
        raise NotImplementedFeature("INDI mount backend not implemented")
