from __future__ import annotations

from dataclasses import asdict
import datetime
from pathlib import Path

from astrolabe.camera import Image, get_camera_backend
from astrolabe.cli.commands import _parse_roi
from astrolabe.cli.output import emit, emit_error
from astrolabe.cli.runtime import handle_error, note_dry_run, prepare
from astrolabe.errors import AstrolabeError
from astrolabe.services.focus import (
    FocusAnalyzer,
    FocusConfig,
    FocusMeasurement,
    FocusService,
)
from astrolabe.services.focus_monitor import FocusMonitor, FocusTrendEstimator


def _focus_analyzer(args) -> FocusAnalyzer:
    return FocusAnalyzer(
        FocusConfig(
            detection_sigma=args.detection_sigma,
            min_stars=args.min_stars,
            saturation_level=args.saturation_level,
        )
    )


def _exposure(args, config) -> float | None:
    if args.exposure is not None:
        return args.exposure
    return config.camera_default_exposure_s


def _run_measure(args, config) -> int:
    note_dry_run(args, "focus measurement")

    try:
        analyzer = _focus_analyzer(args)
        service = FocusService(analyzer=analyzer)

        if args.input_fits:
            path = Path(args.input_fits)
            if not path.is_file():
                return emit_error(
                    args,
                    "focus.measure",
                    code="file_not_found",
                    message=f"Input file not found: {path}",
                )
            image = Image(
                data=str(path),
                width_px=0,
                height_px=0,
                timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
                exposure_s=0.0,
                metadata={},
            )
            result = service.measure_image(image)
        else:
            exposure = _exposure(args, config)
            if exposure is None:
                return emit_error(
                    args,
                    "focus.measure",
                    code="invalid_argument",
                    message=(
                        "Exposure is required (use --exposure or set "
                        "camera.default_exposure_s)."
                    ),
                    exit_code=2,
                )
            roi = _parse_roi(args.roi)
            camera = get_camera_backend(config)
            service = FocusService(camera_backend=camera, analyzer=analyzer)
            result = service.capture_and_measure(
                exposure_s=exposure,
                gain=args.gain,
                binning=args.binning,
                roi=roi,
            )
    except (AstrolabeError, OSError, RuntimeError, ValueError) as exc:
        return emit_error(
            args,
            "focus.measure",
            code="focus_measure_failed",
            message=f"Focus measurement failed: {exc}",
        )

    data = asdict(result)
    if not result.valid:
        return emit_error(
            args,
            "focus.measure",
            code="focus_measurement_invalid",
            message=result.message or "Focus measurement is invalid",
            data=data,
        )

    emit(
        args,
        "focus.measure",
        ok=True,
        data=data,
        human="\n".join(
            [
                f"HFR: {result.hfr_px:.2f} px",
                f"Stars: {result.star_count} accepted, "
                f"{result.rejected_star_count} rejected",
                f"Scatter: {result.hfr_mad_px:.2f} px (MAD)",
            ]
        ),
    )
    return 0


def _monitor_line(result: FocusMeasurement, trend: str | None) -> str:
    if not result.valid or result.hfr_px is None:
        reason = result.message or "invalid measurement"
        return f"HFR --   stars {result.star_count}   invalid: {reason}"

    scatter = "--" if result.hfr_mad_px is None else f"{result.hfr_mad_px:.2f}"
    line = f"HFR {result.hfr_px:.2f} px   stars {result.star_count}   scatter {scatter}"
    if trend is not None:
        line += f"   {trend}"
    return line


def _run_monitor(args, config) -> int:
    if getattr(args, "json", False):
        return emit_error(
            args,
            "focus.monitor",
            code="invalid_argument",
            message="focus monitor is interactive and does not support --json",
            exit_code=2,
        )

    note_dry_run(args, "focus monitoring")

    frame_count = getattr(args, "frames", None)
    if frame_count is not None and frame_count < 1:
        return emit_error(
            args,
            "focus.monitor",
            code="invalid_argument",
            message="--frames must be at least 1",
            exit_code=2,
        )

    exposure = _exposure(args, config)
    if exposure is None:
        return emit_error(
            args,
            "focus.monitor",
            code="invalid_argument",
            message=(
                "Exposure is required (use --exposure or set "
                "camera.default_exposure_s)."
            ),
            exit_code=2,
        )

    try:
        analyzer = _focus_analyzer(args)
        camera = get_camera_backend(config)
        service = FocusService(analyzer=analyzer)
        monitor = FocusMonitor(camera, service)
        trend = FocusTrendEstimator()
        roi = _parse_roi(args.roi)

        with monitor.open(
            exposure_s=exposure,
            gain=args.gain,
            binning=args.binning,
            roi=roi,
            frame_count=frame_count,
        ) as measurements:
            for result in measurements:
                current_trend = trend.update(result)
                print(_monitor_line(result, current_trend), flush=True)
    except KeyboardInterrupt:
        return 0
    except (
        AstrolabeError,
        NotImplementedError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        return emit_error(
            args,
            "focus.monitor",
            code="focus_monitor_failed",
            message=f"Focus monitor failed: {exc}",
        )

    return 0


def run_focus(args) -> int:
    """Run one-shot or live focus measurement."""

    try:
        config = prepare(args)
        if args.action == "measure":
            return _run_measure(args, config)
        if args.action == "monitor":
            return _run_monitor(args, config)
    except AstrolabeError as exc:
        return handle_error(args, f"focus.{args.action}", exc)
    return emit_error(
        args,
        "focus",
        code="invalid_argument",
        message=f"Unknown focus action: {args.action}",
        exit_code=2,
    )
