from __future__ import annotations

import datetime
import subprocess
import time
from pathlib import Path

from astrolabe.errors import BackendError
from astrolabe.indi import IndiClient

from .base import CameraBackend, LiveFrameSession
from .indi_live import IndiLiveFrameSession
from .types import Image

DEFAULT_CAPTURE_TIMEOUT_S = 60.0


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
        self._live_session: IndiLiveFrameSession | None = None

    def connect(self) -> None:
        self._client.wait_for_device(self.device)
        self._client.setprop(f"{self.device}.CONNECTION.CONNECT", "On", soft=False)
        time.sleep(0.2)
        self._resolve_gain_property()
        if self.output_dir is not None:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self._ensure_upload_settings()
        self._connected = True

    def disconnect(self) -> None:
        if self._live_session is not None:
            self._live_session.close()
        if not self._connected:
            return
        self._client.setprop(f"{self.device}.CONNECTION.DISCONNECT", "On", soft=True)
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def _resolve_gain_property(self) -> None:
        if self._gain_prop is not None:
            return
        if self._client.has_prop(f"{self.device}.CCD_GAIN.GAIN"):
            self._gain_prop = "CCD_GAIN.GAIN"
        elif self._client.has_prop(f"{self.device}.CCD_GAIN.VALUE"):
            self._gain_prop = "CCD_GAIN.VALUE"

    @staticmethod
    def _validate_capture_controls(
        gain: float | None,
        binning: int | None,
        roi: tuple[int, int, int, int] | None,
    ) -> None:
        if binning is not None and binning <= 0:
            raise ValueError("binning must be > 0")
        if roi is not None and (roi[2] <= 0 or roi[3] <= 0):
            raise ValueError("ROI width and height must be > 0")

    def _configure_capture_controls(
        self,
        gain: float | None,
        binning: int | None,
        roi: tuple[int, int, int, int] | None,
    ) -> None:
        if gain is not None:
            self._resolve_gain_property()
            if self._gain_prop is not None:
                self._client.setprop(
                    f"{self.device}.{self._gain_prop}", str(gain), soft=True
                )

        if binning is not None:
            self._client.setprop(
                f"{self.device}.CCD_BINNING.HOR_BIN", str(binning), soft=True
            )
            self._client.setprop(
                f"{self.device}.CCD_BINNING.VER_BIN", str(binning), soft=True
            )

        if roi is not None:
            x, y, w, h = roi
            self._client.setprop(f"{self.device}.CCD_FRAME.X", str(x), soft=True)
            self._client.setprop(f"{self.device}.CCD_FRAME.Y", str(y), soft=True)
            self._client.setprop(f"{self.device}.CCD_FRAME.WIDTH", str(w), soft=True)
            self._client.setprop(f"{self.device}.CCD_FRAME.HEIGHT", str(h), soft=True)

    def capture(
        self,
        exposure_s: float,
        gain: float | None = None,
        binning: int | None = None,
        roi: tuple[int, int, int, int] | None = None,
    ) -> Image:
        if self._live_session is not None:
            raise BackendError("camera is owned by an active live-frame session")
        if not self._connected:
            self.connect()
        elif self.output_dir is not None:
            # Some simulators reset upload mode/prefix between captures.
            self._ensure_upload_settings()

        self._configure_capture_controls(gain, binning, roi)

        file_path_prop = f"{self.device}.CCD_FILE_PATH.FILE_PATH"
        base_path: Path | None = None
        last_path_str = ""
        pre_capture_mtimes: dict[Path, float] = {}

        # Snapshot the currently advertised output before starting the exposure.
        # If the driver reuses a filename, the completed capture must advance its
        # mtime; this prevents a recently written previous exposure from being
        # mistaken for the new one.
        if self._client.has_prop(file_path_prop):
            try:
                last_path_str = self._client.getprop_value(file_path_prop)
            except subprocess.CalledProcessError:
                last_path_str = ""
        if last_path_str:
            candidate = Path(last_path_str)
            if candidate.is_dir():
                raise RuntimeError(f"CCD_FILE_PATH is a directory: {candidate}")
            base_path = candidate
            if candidate.exists():
                pre_capture_mtimes[candidate] = candidate.stat().st_mtime
        elif self.output_dir is not None:
            candidate = self.output_dir / f"{self.output_prefix}.fits"
            base_path = candidate
            if candidate.exists():
                pre_capture_mtimes[candidate] = candidate.stat().st_mtime

        exposure_prop = (
            "GUIDER_EXPOSURE.GUIDER_EXPOSURE_VALUE"
            if self.use_guider_exposure
            else "CCD_EXPOSURE.CCD_EXPOSURE_VALUE"
        )
        self._client.setprop(
            f"{self.device}.{exposure_prop}", f"{exposure_s}", soft=False
        )
        timeout_s = max(DEFAULT_CAPTURE_TIMEOUT_S, exposure_s + 5.0)
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self._client.has_prop(file_path_prop):
                try:
                    path_str = self._client.getprop_value(file_path_prop)
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
                    last_path_str = path_str
            elif base_path is None and self.output_dir is not None:
                base_path = self.output_dir / f"{self.output_prefix}.fits"

            if base_path and base_path.exists():
                mt = base_path.stat().st_mtime
                previous_mt = pre_capture_mtimes.get(base_path)
                if previous_mt is None or mt > previous_mt:
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

    def live_frames(
        self,
        exposure_s: float,
        gain: float | None = None,
        binning: int | None = None,
        roi: tuple[int, int, int, int] | None = None,
        frame_count: int | None = None,
    ) -> LiveFrameSession:
        if self._live_session is not None:
            raise BackendError("camera already has an active live-frame session")
        if not self._connected:
            self.connect()
        self._validate_capture_controls(gain, binning, roi)

        def release() -> None:
            self._live_session = None
            if self.output_dir is not None:
                self._ensure_upload_settings()

        session = IndiLiveFrameSession(
            client=self._client,
            host=self.host,
            port=self.port,
            device=self.device,
            use_guider_exposure=self.use_guider_exposure,
            exposure_s=exposure_s,
            frame_count=frame_count,
            configure_camera=lambda: self._configure_capture_controls(
                gain, binning, roi
            ),
            on_close=release,
        )
        self._live_session = session
        return session

    def _ensure_upload_settings(self) -> None:
        output_dir = self.output_dir
        if output_dir is None:
            return
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
            str(output_dir.resolve()),
            soft=True,
        )
        self._client.setprop(
            f"{self.device}.UPLOAD_SETTINGS.UPLOAD_PREFIX",
            self.output_prefix,
            soft=True,
        )
