from __future__ import annotations

import datetime
import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

from astrolabe.solver.types import Image
from .base import CameraBackend

DEFAULT_CAPTURE_TIMEOUT_S = 60.0
CCD_FILE_PATH_RETRY_COUNT = 10
CCD_FILE_PATH_RETRY_SLEEP_S = 0.2
DEVICE_POLL_TIMEOUT_S = 1.0


def _run_indi(tool: str, host: str, port: int, args: list[str], *, check: bool = True, capture: bool = False):
    cmd = [tool, "-h", host, "-p", str(port)] + args
    if capture:
        return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return subprocess.run(cmd, check=check)


def _getprop_value(host: str, port: int, query: str, *, timeout_s: float = 2.0) -> str:
    cp = subprocess.run(
        ["indi_getprop", "-h", host, "-p", str(port), "-t", str(timeout_s), "-1", query],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return cp.stdout.strip()


def _has_prop(host: str, port: int, query: str, *, timeout_s: float = 2.0) -> bool:
    cp = subprocess.run(
        ["indi_getprop", "-h", host, "-p", str(port), "-t", str(timeout_s), "-1", query],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return cp.returncode == 0 and bool(cp.stdout.strip())


def _setprop(host: str, port: int, prop: str, value: str, *, soft: bool = True) -> None:
    try:
        _run_indi("indi_setprop", host, port, [f"{prop}={value}"], check=True, capture=False)
    except subprocess.CalledProcessError as e:
        if not soft:
            raise
        logging.warning(f"Could not set {prop}={value} (may be unavailable): {e}")


def _wait_for_device(host: str, port: int, device: str, timeout_s: float = 10.0) -> None:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = subprocess.run(
            ["indi_getprop", "-h", host, "-p", str(port), "-t", str(DEVICE_POLL_TIMEOUT_S), "-1"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if last.returncode in (0, 1) and f"{device}." in (last.stdout or ""):
            return
        time.sleep(0.2)

    stderr = (last.stderr.strip() if last else "")
    raise RuntimeError(
        f"Timed out waiting for INDI device '{device}' on {host}:{port}. stderr={stderr!r}"
    )


def _wait_for_mtime_increase(path: Path, prev_mtime: Optional[float], timeout_s: float) -> float:
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
        self.output_dir = output_dir
        self.output_prefix = output_prefix or "astrolabe_capture_"
        self.use_guider_exposure = use_guider_exposure
        self._connected = False
        self._gain_prop: str | None = None

    def connect(self) -> None:
        _wait_for_device(self.host, self.port, self.device)
        _setprop(self.host, self.port, f"{self.device}.CONNECTION.CONNECT", "On", soft=False)
        time.sleep(0.2)
        if _has_prop(self.host, self.port, f"{self.device}.CCD_GAIN.GAIN"):
            self._gain_prop = "CCD_GAIN.GAIN"
        elif _has_prop(self.host, self.port, f"{self.device}.CCD_GAIN.VALUE"):
            self._gain_prop = "CCD_GAIN.VALUE"
        if self.output_dir is not None:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            _setprop(self.host, self.port, f"{self.device}.UPLOAD_MODE.UPLOAD_LOCAL", "On", soft=True)
            _setprop(self.host, self.port, f"{self.device}.UPLOAD_MODE.UPLOAD_CLIENT", "Off", soft=True)
            _setprop(self.host, self.port, f"{self.device}.UPLOAD_MODE.UPLOAD_BOTH", "Off", soft=True)
            _setprop(
                self.host,
                self.port,
                f"{self.device}.UPLOAD_SETTINGS.UPLOAD_DIR",
                str(self.output_dir.resolve()),
                soft=True,
            )
            _setprop(
                self.host,
                self.port,
                f"{self.device}.UPLOAD_SETTINGS.UPLOAD_PREFIX",
                self.output_prefix,
                soft=True,
            )
        self._connected = True

    def disconnect(self) -> None:
        if not self._connected:
            return
        _setprop(self.host, self.port, f"{self.device}.CONNECTION.DISCONNECT", "On", soft=True)
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

        if gain is not None:
            if self._gain_prop is None:
                if _has_prop(self.host, self.port, f"{self.device}.CCD_GAIN.GAIN"):
                    self._gain_prop = "CCD_GAIN.GAIN"
                elif _has_prop(self.host, self.port, f"{self.device}.CCD_GAIN.VALUE"):
                    self._gain_prop = "CCD_GAIN.VALUE"
            if self._gain_prop is not None:
                _setprop(self.host, self.port, f"{self.device}.{self._gain_prop}", str(gain), soft=True)

        if binning is not None:
            _setprop(self.host, self.port, f"{self.device}.CCD_BINNING.HOR_BIN", str(binning), soft=True)
            _setprop(self.host, self.port, f"{self.device}.CCD_BINNING.VERT_BIN", str(binning), soft=True)

        if roi is not None:
            x, y, w, h = roi
            _setprop(self.host, self.port, f"{self.device}.CCD_FRAME.X", str(x), soft=True)
            _setprop(self.host, self.port, f"{self.device}.CCD_FRAME.Y", str(y), soft=True)
            _setprop(self.host, self.port, f"{self.device}.CCD_FRAME.WIDTH", str(w), soft=True)
            _setprop(self.host, self.port, f"{self.device}.CCD_FRAME.HEIGHT", str(h), soft=True)

        base_path_str = ""
        for _ in range(CCD_FILE_PATH_RETRY_COUNT):
            if _has_prop(self.host, self.port, f"{self.device}.CCD_FILE_PATH.FILE_PATH"):
                try:
                    base_path_str = _getprop_value(self.host, self.port, f"{self.device}.CCD_FILE_PATH.FILE_PATH")
                except subprocess.CalledProcessError:
                    base_path_str = ""
            else:
                base_path_str = ""
            if base_path_str:
                break
            time.sleep(CCD_FILE_PATH_RETRY_SLEEP_S)
        if not base_path_str:
            if self.output_dir is not None:
                base_path = self.output_dir / f"{self.output_prefix}.fits"
            else:
                raise RuntimeError("CCD_FILE_PATH is empty; camera may not support local file uploads.")
        else:
            base_path = Path(base_path_str)
        if base_path.is_dir():
            raise RuntimeError(f"CCD_FILE_PATH is a directory: {base_path}")
        prev_mtime = base_path.stat().st_mtime if base_path.exists() else None

        exposure_prop = (
            "GUIDER_EXPOSURE.GUIDER_EXPOSURE_VALUE"
            if self.use_guider_exposure
            else "CCD_EXPOSURE.CCD_EXPOSURE_VALUE"
        )
        _setprop(self.host, self.port, f"{self.device}.{exposure_prop}", f"{exposure_s}", soft=False)

        timeout_s = max(DEFAULT_CAPTURE_TIMEOUT_S, exposure_s + 5.0)
        _wait_for_mtime_increase(base_path, prev_mtime, timeout_s=timeout_s)

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
