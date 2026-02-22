from __future__ import annotations

import datetime
import subprocess
import time
from pathlib import Path
from typing import Optional

from astrolabe.solver.types import Image
from astrolabe.indi import IndiClient
from .base import CameraBackend

DEFAULT_CAPTURE_TIMEOUT_S = 60.0
CCD_FILE_PATH_RETRY_COUNT = 10
CCD_FILE_PATH_RETRY_SLEEP_S = 0.2


def _wait_for_mtime_increase(
    path: Path, prev_mtime: Optional[float], timeout_s: float
) -> float:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if path.exists():
            mt = path.stat().st_mtime
            if prev_mtime is None or mt > prev_mtime:
                return mt
        time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for {path} to update")


class IndiCameraBackend(CameraBackend):
    def __init__(
        self,
        host: str,
        port: int,
        device: str,
        output_dir: Path | None = None,
        output_prefix: str | None = None,
        use_guider_exposure: bool = False,
    ):
        self.host = host
        self.port = port
        self.device = device
        self._client = IndiClient(host, port)
        self.output_dir = output_dir
        self.output_prefix = output_prefix or "astrolabe_capture_"
        self.use_guider_exposure = use_guider_exposure
        self._connected = False
        self._gain_prop: str | None = None

    def connect(self) -> None:
        self._client.wait_for_device(self.device)
        self._client.setprop(f"{self.device}.CONNECTION.CONNECT", "On", soft=False)
        time.sleep(0.2)
        if self._client.has_prop(f"{self.device}.CCD_GAIN.GAIN"):
            self._gain_prop = "CCD_GAIN.GAIN"
        elif self._client.has_prop(f"{self.device}.CCD_GAIN.VALUE"):
            self._gain_prop = "CCD_GAIN.VALUE"
        if self.output_dir is not None:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self._ensure_upload_settings()
        self._connected = True

    def disconnect(self) -> None:
        if not self._connected:
            return
        self._client.setprop(f"{self.device}.CONNECTION.DISCONNECT", "On", soft=True)
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def capture(
        self,
        exposure_s: float,
        gain: float | None = None,
        binning: int | None = None,
        roi: tuple[int, int, int, int] | None = None,
    ) -> Image:
        if not self._connected:
            self.connect()
        elif self.output_dir is not None:
            # Some simulators reset upload mode/prefix between captures.
            self._ensure_upload_settings()

        if gain is not None:
            if self._gain_prop is None:
                if self._client.has_prop(f"{self.device}.CCD_GAIN.GAIN"):
                    self._gain_prop = "CCD_GAIN.GAIN"
                elif self._client.has_prop(f"{self.device}.CCD_GAIN.VALUE"):
                    self._gain_prop = "CCD_GAIN.VALUE"
            if self._gain_prop is not None:
                self._client.setprop(
                    f"{self.device}.{self._gain_prop}", str(gain), soft=True
                )

        if binning is not None:
            self._client.setprop(
                f"{self.device}.CCD_BINNING.HOR_BIN", str(binning), soft=True
            )
            self._client.setprop(
                f"{self.device}.CCD_BINNING.VERT_BIN", str(binning), soft=True
            )

        if roi is not None:
            x, y, w, h = roi
            self._client.setprop(f"{self.device}.CCD_FRAME.X", str(x), soft=True)
            self._client.setprop(f"{self.device}.CCD_FRAME.Y", str(y), soft=True)
            self._client.setprop(f"{self.device}.CCD_FRAME.WIDTH", str(w), soft=True)
            self._client.setprop(f"{self.device}.CCD_FRAME.HEIGHT", str(h), soft=True)

        exposure_prop = (
            "GUIDER_EXPOSURE.GUIDER_EXPOSURE_VALUE"
            if self.use_guider_exposure
            else "CCD_EXPOSURE.CCD_EXPOSURE_VALUE"
        )
        exposure_start = time.time()
        self._client.setprop(
            f"{self.device}.{exposure_prop}", f"{exposure_s}", soft=False
        )
        timeout_s = max(DEFAULT_CAPTURE_TIMEOUT_S, exposure_s + 5.0)
        deadline = time.time() + timeout_s
        base_path: Path | None = None
        prev_mtime: float | None = None
        last_path_str = ""
        while time.time() < deadline:
            if self._client.has_prop(f"{self.device}.CCD_FILE_PATH.FILE_PATH"):
                try:
                    path_str = self._client.getprop_value(
                        f"{self.device}.CCD_FILE_PATH.FILE_PATH"
                    )
                except subprocess.CalledProcessError:
                    path_str = ""
            else:
                path_str = ""

            if path_str:
                if path_str != last_path_str:
                    candidate = Path(path_str)
                    if candidate.is_dir():
                        raise RuntimeError(f"CCD_FILE_PATH is a directory: {candidate}")
                    base_path = candidate
                    prev_mtime = (
                        base_path.stat().st_mtime if base_path.exists() else None
                    )
                    last_path_str = path_str
            elif base_path is None and self.output_dir is not None:
                candidate = self.output_dir / f"{self.output_prefix}.fits"
                base_path = candidate
                prev_mtime = base_path.stat().st_mtime if base_path.exists() else None

            if base_path and base_path.exists():
                mt = base_path.stat().st_mtime
                if prev_mtime is None or mt > prev_mtime or mt >= exposure_start - 0.5:
                    break
            time.sleep(0.1)

        if base_path is None or not base_path.exists():
            raise RuntimeError("Timed out waiting for CCD_FILE_PATH to produce a file")

        return Image(
            data=str(base_path),
            width_px=0,
            height_px=0,
            timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
            exposure_s=exposure_s,
            metadata={
                "device": self.device,
                "indi_host": self.host,
                "indi_port": self.port,
                "use_guider_exposure": self.use_guider_exposure,
            },
        )

    def _ensure_upload_settings(self) -> None:
        self._client.setprop(
            f"{self.device}.UPLOAD_MODE.UPLOAD_LOCAL", "On", kind="s", soft=True
        )
        self._client.setprop(
            f"{self.device}.UPLOAD_MODE.UPLOAD_CLIENT", "Off", kind="s", soft=True
        )
        self._client.setprop(
            f"{self.device}.UPLOAD_MODE.UPLOAD_BOTH", "Off", kind="s", soft=True
        )
        self._client.setprop(
            f"{self.device}.UPLOAD_SETTINGS.UPLOAD_DIR",
            str(self.output_dir.resolve()),
            soft=True,
        )
        self._client.setprop(
            f"{self.device}.UPLOAD_SETTINGS.UPLOAD_PREFIX",
            self.output_prefix,
            soft=True,
        )
