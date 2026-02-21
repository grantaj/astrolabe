from abc import ABC, abstractmethod
from dataclasses import dataclass
import datetime


@dataclass
class MountState:
    connected: bool
    ra_rad: float | None
    dec_rad: float | None
    tracking: bool
    slewing: bool
    timestamp_utc: datetime.datetime


class MountBackend(ABC):
    @abstractmethod
    def connect(self) -> None:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        pass

    @abstractmethod
    def get_state(self) -> MountState:
        pass

    @abstractmethod
    def slew_to(self, ra_rad: float, dec_rad: float) -> None:
        pass

    @abstractmethod
    def sync(self, ra_rad: float, dec_rad: float) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def park(self) -> None:
        pass

    @abstractmethod
    def set_tracking(self, enabled: bool) -> None:
        pass

    @abstractmethod
    def pulse_guide(self, ra_ms: float, dec_ms: float) -> None:
        pass
