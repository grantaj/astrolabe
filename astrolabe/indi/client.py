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

    def getprop_state(self, query: str, *, timeout_s: float = 2.0) -> str:
        """Return the INDI property state (Idle, Ok, Busy, Alert)."""
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
                "-s",
                query,
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        line = cp.stdout.strip().split("\n")[0]
        return line.split()[0] if line else ""

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

    def setprop(
        self, prop: str, value: str, *, kind: str | None = None, soft: bool = True
    ) -> None:
        try:
            # indi_setprop accepts spaces in property specs passed as a single argv.
            args = [f"{prop}={value}"]
            if kind in {"n", "s", "x"}:
                args = [f"-{kind}", *args]
            self.run("indi_setprop", args, check=True, capture=False)
        except subprocess.CalledProcessError as e:
            if not soft:
                raise
            logging.warning(f"Could not set {prop}={value} (may be unavailable): {e}")

    def setprop_multi(
        self, props: dict[str, str], *, kind: str | None = None, soft: bool = True
    ) -> None:
        # indi_setprop accepts spaces in property specs passed as a single argv.
        # Use individual specs: device.property.element=value
        args = [f"{prop}={value}" for prop, value in props.items()]
        if kind in {"n", "s", "x"}:
            args = [f"-{kind}", *args]
        try:
            self.run("indi_setprop", args, check=True, capture=False)
        except subprocess.CalledProcessError as e:
            if not soft:
                raise
            logging.warning(
                f"Could not set properties {props} (may be unavailable): {e}"
            )

    def setprop_vector(
        self,
        device: str,
        prop: str,
        elements: dict[str, str],
        *,
        kind: str | None = None,
        soft: bool = True,
        order: list[str] | None = None,
    ) -> None:
        # indi_setprop vector spec: device.property.e1;e2=v1;v2
        if order is None:
            order = list(elements.keys())
        elem_names = ";".join(order)
        elem_values = ";".join(elements[name] for name in order)
        spec = f"{device}.{prop}.{elem_names}={elem_values}"
        args = [spec]
        if kind in {"n", "s", "x"}:
            args = [f"-{kind}", *args]
        try:
            self.run("indi_setprop", args, check=True, capture=False)
        except subprocess.CalledProcessError as e:
            if not soft:
                raise
            logging.warning(f"Could not set vector {spec} (may be unavailable): {e}")

    def snapshot(self, device: str, *, timeout_s: float = 2.0) -> dict[str, str]:
        """Fetch all property values and states for a device in one query."""
        cp = subprocess.run(
            [
                "indi_getprop",
                "-h",
                self.host,
                "-p",
                str(self.port),
                "-t",
                str(timeout_s),
                f"{device}.*.*",
                f"{device}.*._STATE",
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        result: dict[str, str] = {}
        for line in cp.stdout.splitlines():
            eq = line.find("=")
            if eq < 0:
                continue
            result[line[:eq]] = line[eq + 1 :]
        return result

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

        stderr = last.stderr.strip() if last else ""
        raise RuntimeError(
            "Timed out waiting for INDI device "
            f"'{device}' on {self.host}:{self.port}. stderr={stderr!r}"
        )
