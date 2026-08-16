#!/usr/bin/env python3
from __future__ import annotations

import argparse
import statistics
import tempfile
import time
from pathlib import Path

from astrolabe.camera.indi import IndiCameraBackend
from astrolabe.indi import IndiClient


def _measure_legacy(
    camera: IndiCameraBackend,
    frames: int,
    exposure_s: float,
    binning: int,
    roi: tuple[int, int, int, int],
) -> list[float]:
    samples: list[float] = []
    for _ in range(frames):
        started = time.perf_counter()
        camera.capture(exposure_s=exposure_s, binning=binning, roi=roi)
        samples.append(time.perf_counter() - started)
    return samples


def _measure_live(
    camera: IndiCameraBackend,
    frames: int,
    exposure_s: float,
    binning: int,
    roi: tuple[int, int, int, int],
) -> list[float]:
    samples: list[float] = []
    with camera.live_frames(
        exposure_s=exposure_s,
        binning=binning,
        roi=roi,
        frame_count=frames,
    ) as sequence:
        for _ in range(frames):
            started = time.perf_counter()
            next(sequence)
            samples.append(time.perf_counter() - started)
    return samples


def _report(label: str, samples: list[float], exposure_s: float) -> float:
    steady = samples[min(5, len(samples) - 1) :]
    median_total = statistics.median(steady)
    median_overhead = median_total - exposure_s
    print(
        f"{label}: median total={median_total * 1000:.1f} ms, "
        f"median non-exposure overhead={median_overhead * 1000:.1f} ms, "
        f"frames={len(samples)}"
    )
    return median_total


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Astrolabe one-shot and live INDI camera capture latency."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7624)
    parser.add_argument("--device", default="CCD Simulator")
    parser.add_argument("--frames", type=int, default=25)
    parser.add_argument("--exposure", type=float, default=0.01)
    parser.add_argument("--binning", type=int, default=2)
    parser.add_argument("--roi", nargs=4, type=int, default=(0, 0, 320, 240))
    parser.add_argument(
        "--polling-ms",
        type=int,
        help=(
            "set the INDI device polling period before benchmarking; "
            "use 25 for the CCD Simulator to avoid measuring its stock 1 s timer"
        ),
    )
    args = parser.parse_args()
    if args.frames < 20:
        parser.error(
            "--frames must be at least 20 to distinguish startup from steady state"
        )
    if args.polling_ms is not None and args.polling_ms < 10:
        parser.error("--polling-ms must be at least 10")

    if args.polling_ms is not None:
        client = IndiClient(args.host, args.port)
        client.wait_for_device(args.device)
        client.setprop(
            f"{args.device}.POLLING_PERIOD.PERIOD_MS",
            str(args.polling_ms),
            kind="n",
            soft=False,
        )

    with tempfile.TemporaryDirectory(prefix="astrolabe-camera-bench-") as directory:
        camera = IndiCameraBackend(
            host=args.host,
            port=args.port,
            device=args.device,
            output_dir=Path(directory),
            output_prefix="benchmark_",
        )
        roi = tuple(args.roi)
        try:
            legacy = _measure_legacy(
                camera, args.frames, args.exposure, args.binning, roi
            )
            live = _measure_live(camera, args.frames, args.exposure, args.binning, roi)
        finally:
            camera.disconnect()

    legacy_median = _report("legacy capture", legacy, args.exposure)
    live_median = _report("live BLOB", live, args.exposure)
    print(f"speedup: {legacy_median / live_median:.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
