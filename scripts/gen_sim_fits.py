#!/usr/bin/env python3
"""Generate FITS test frames from INDI 'CCD Simulator' using indi_setprop/indi_getprop.

This version avoids relying on any driver-side auto-numbering. The CCD Simulator
writes to a fixed FILE_PATH (derived from UPLOAD_DIR + UPLOAD_PREFIX). We:
  1) trigger an exposure
  2) wait for the fixed FILE_PATH to update (mtime increases)
  3) copy the updated file to a uniquely numbered filename

Prereqs:
  - indiserver running:
      indiserver indi_simulator_ccd
  - indi-bin installed (indi_getprop, indi_setprop)

Usage:
  python scripts/gen_sim_fits.py --count 5 --exposure 2.0 --outdir testdata/raw
  python scripts/gen_sim_fits.py --guider --count 10 --exposure 1.0 --outdir testdata/raw
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional


DEVICE = "CCD Simulator"


def run_indi(tool: str, host: str, port: int, args: list[str], *, check: bool = True, capture: bool = False):
    cmd = [tool, "-h", host, "-p", str(port)] + args
    if capture:
        return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return subprocess.run(cmd, check=check)


def getprop_value(host: str, port: int, query: str, *, timeout_s: float = 2.0) -> str:
    """Get a single INDI property value using -1 (expects exactly one match)."""
    cp = subprocess.run(
        ["indi_getprop", "-h", host, "-p", str(port), "-t", str(timeout_s), "-1", query],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return cp.stdout.strip()


def setprop(host: str, port: int, prop: str, value: str, *, soft: bool = True) -> None:
    try:
        run_indi("indi_setprop", host, port, [f"{prop}={value}"], check=True, capture=False)
    except subprocess.CalledProcessError as e:
        if not soft:
            raise
        print(f"[warn] Could not set {prop}={value} (may be unavailable): {e}")


def wait_for_device(host: str, port: int, timeout_s: float = 10.0) -> None:
    """Wait until the device appears in indi_getprop output."""
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = run_indi("indi_getprop", host, port, [], check=False, capture=True)
        # indi_getprop can return 0 or 1 in normal situations; treat both as "not fatal"
        if last.returncode in (0, 1) and f"{DEVICE}." in (last.stdout or ""):
            return
        time.sleep(0.2)

    stderr = (last.stderr.strip() if last else "")
    raise RuntimeError(
        f"Timed out waiting for INDI device '{DEVICE}' on {host}:{port}. stderr={stderr!r}"
    )


def wait_for_mtime_increase(path: Path, prev_mtime: Optional[float], timeout_s: float) -> float:
    """Wait until 'path' exists and its mtime increases compared to prev_mtime."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if path.exists():
            mt = path.stat().st_mtime
            if prev_mtime is None or mt > prev_mtime:
                return mt
        time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for {path} to update")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--indi-host", default="127.0.0.1")
    ap.add_argument("--indi-port", type=int, default=7624)

    ap.add_argument("--count", type=int, default=3, help="Number of FITS frames to generate")
    ap.add_argument("--exposure", type=float, default=2.0, help="Exposure time in seconds")
    ap.add_argument("--outdir", type=Path, default=Path("testdata/raw"), help="Output directory for FITS")
    ap.add_argument("--prefix", type=str, default="astrolabe_sim_", help="Output filename prefix for numbered copies")
    ap.add_argument("--settle", type=float, default=0.3, help="Extra seconds to wait after each exposure update")
    ap.add_argument("--guider", action="store_true", help="Use GUIDER_EXPOSURE instead of CCD_EXPOSURE (smaller frames)")

    args = ap.parse_args()

    host = args.indi_host
    port = args.indi_port

    outdir: Path = args.outdir
    outdir.mkdir(parents=True, exist_ok=True)

    wait_for_device(host, port)

    # Ensure device connected
    setprop(host, port, f"{DEVICE}.CONNECTION.CONNECT", "On", soft=False)
    time.sleep(0.2)

    # Configure local upload directory/prefix (driver-managed base filename; may still be fixed)
    setprop(host, port, f"{DEVICE}.UPLOAD_MODE.UPLOAD_LOCAL", "On", soft=True)
    setprop(host, port, f"{DEVICE}.UPLOAD_MODE.UPLOAD_CLIENT", "Off", soft=True)
    setprop(host, port, f"{DEVICE}.UPLOAD_MODE.UPLOAD_BOTH", "Off", soft=True)
    setprop(host, port, f"{DEVICE}.UPLOAD_SETTINGS.UPLOAD_DIR", str(outdir.resolve()), soft=True)
    setprop(host, port, f"{DEVICE}.UPLOAD_SETTINGS.UPLOAD_PREFIX", args.prefix, soft=True)

    # Discover the driver-managed base output path from INDI (authoritative)
    base_path_str = getprop_value(host, port, f"{DEVICE}.CCD_FILE_PATH.FILE_PATH")
    base_path = Path(base_path_str)

    print(f"[info] INDI: {host}:{port}  device: {DEVICE}")
    print(f"[info] Driver output FILE_PATH: {base_path}")
    print(f"[info] Copying numbered FITS into: {outdir.resolve()}")
    print(f"[info] Generating {args.count} frame(s) at {args.exposure:.2f}s ({'GUIDER' if args.guider else 'CCD'})")

    prev_mtime = base_path.stat().st_mtime if base_path.exists() else None
    exposure_prop = "GUIDER_EXPOSURE.GUIDER_EXPOSURE_VALUE" if args.guider else "CCD_EXPOSURE.CCD_EXPOSURE_VALUE"

    for i in range(args.count):
        setprop(host, port, f"{DEVICE}.{exposure_prop}", f"{args.exposure}", soft=False)

        # Wait for base file to update, then snapshot it
        prev_mtime = wait_for_mtime_increase(base_path, prev_mtime, timeout_s=max(10.0, args.exposure + 5.0))
        time.sleep(args.settle)

        dst = outdir / f"{args.prefix}{i+1:04d}.fits"
        shutil.copy2(base_path, dst)
        print(f"[ok] Wrote FITS: {dst.name}")

    print("[done] FITS generation complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
