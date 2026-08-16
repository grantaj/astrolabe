from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator

from astrolabe.solver.types import Image


@dataclass(frozen=True)
class FitsImageData:
    """An in-memory, uncompressed FITS image payload."""

    data: bytes


class LiveFrameSession(ABC, Iterator[Image]):
    """Synchronous, single-consumer sequence of complete camera frames."""

    def __iter__(self) -> LiveFrameSession:
        return self

    def __enter__(self) -> LiveFrameSession:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @abstractmethod
    def __next__(self) -> Image:
        pass

    @abstractmethod
    def close(self) -> None:
        pass


class CameraBackend(ABC):
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
    def capture(
        self,
        exposure_s: float,
        gain: float | None = None,
        binning: int | None = None,
        roi: tuple[int, int, int, int] | None = None,
    ) -> Image:
        pass

    def live_frames(
        self,
        exposure_s: float,
        gain: float | None = None,
        binning: int | None = None,
        roi: tuple[int, int, int, int] | None = None,
        frame_count: int | None = None,
    ) -> LiveFrameSession:
        """Open a low-overhead synchronous live-frame session."""

        raise NotImplementedError(
            "live frames are not supported by this camera backend"
        )
