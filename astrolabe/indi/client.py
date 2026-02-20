from __future__ import annotations

import logging
import subprocess
import time

DEVICE_POLL_TIMEOUT_S = 1.0


class IndiClient:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    def run(
        self,
        tool: str,
        args: list[str],
        *,
        check: bool = True,
        capture: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        cmd = [tool, "-h", self.host, "-p", str(self.port)] + args
        if capture:
            return subprocess.run(
                cmd,
                check=check,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        return subprocess.run(cmd, check=check, text=True)

    def getprop_value(self, query: str, *, timeout_s: float = 2.0) -> str:
        cp = subprocess.run(
            [
                "indi_getprop",
                "-h",
                self.host,
                "-p",
                str(self.port),
                "-t",
                str(timeout_s),
                "-1",
                query,
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return cp.stdout.strip()

    def has_prop(self, query: str, *, timeout_s: float = 2.0) -> bool:
        cp = subprocess.run(
            [
                "indi_getprop",
                "-h",
                self.host,
                "-p",
                str(self.port),
                "-t",
                str(timeout_s),
                "-1",
                query,
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return cp.returncode == 0 and bool(cp.stdout.strip())

    def setprop(self, prop: str, value: str, *, soft: bool = True) -> None:
        try:
            self.run("indi_setprop", [f"{prop}={value}"], check=True, capture=False)
        except subprocess.CalledProcessError as e:
            if not soft:
                raise
            logging.warning(f"Could not set {prop}={value} (may be unavailable): {e}")

    def wait_for_device(self, device: str, *, timeout_s: float = 10.0) -> None:
        deadline = time.time() + timeout_s
        last = None
        while time.time() < deadline:
            last = subprocess.run(
                [
                    "indi_getprop",
                    "-h",
                    self.host,
                    "-p",
                    str(self.port),
                    "-t",
                    str(DEVICE_POLL_TIMEOUT_S),
                    "-1",
                ],
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
            f"Timed out waiting for INDI device '{device}' on {self.host}:{self.port}. stderr={stderr!r}"
        )
