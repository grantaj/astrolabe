from __future__ import annotations

from dataclasses import asdict
import datetime
import json
from pathlib import Path
import sys

from astrolabe.camera import get_camera_backend
from astrolabe.cli.commands import (
    _config_path_from_args,
    _init_logging,
    _json_envelope,
    _parse_roi,
)
from astrolabe.config import load_config
from astrolabe.services.focus import FocusAnalyzer, FocusConfig, FocusService
from astrolabe.solver.types import Image


def _emit_failure(args, *, code: str, message: str, data=None) -> int:
    if getattr(args, "json", False):
        payload = _json_envelope(
            command="focus.measure",
            ok=False,
            data=data,
            error={"code": code, "message": message, "details": None},
        )
        print(json.dumps(payload, indent=2))
    else:
        print(message, file=sys.stderr)
    return 1


def run_focus(args) -> int:
    """Measure focus once; low-latency continuous monitoring belongs to #40."""

    _init_logging(getattr(args, "log_level", None))
    config = load_config(_config_path_from_args(args))
    if getattr(args, "dry_run", False):
        print("--dry-run has no effect for focus measurement.", file=sys.stderr)

    try:
        focus_config = FocusConfig(
            detection_sigma=args.detection_sigma,
            min_stars=args.min_stars,
            saturation_level=args.saturation_level,
        )
        analyzer = FocusAnalyzer(focus_config)
        service = FocusService(analyzer=analyzer)

        if args.input_fits:
            path = Path(args.input_fits)
            if not path.is_file():
                return _emit_failure(
                    args,
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
            exposure = (
                args.exposure
                if args.exposure is not None
                else config.camera_default_exposure_s
            )
            if exposure is None:
                message = (
                    "Exposure is required (use --exposure or set "
                    "camera.default_exposure_s)."
                )
                if getattr(args, "json", False):
                    payload = _json_envelope(
                        command="focus.measure",
                        ok=False,
                        data=None,
                        error={
                            "code": "invalid_argument",
                            "message": message,
                            "details": None,
                        },
                    )
                    print(json.dumps(payload, indent=2))
                else:
                    print(message, file=sys.stderr)
                return 2
            roi = _parse_roi(args.roi)
            camera = get_camera_backend(config)
            service = FocusService(camera_backend=camera, analyzer=analyzer)
            result = service.capture_and_measure(
                exposure_s=exposure,
                gain=args.gain,
                binning=args.binning,
                roi=roi,
            )
    except (OSError, RuntimeError, ValueError) as exc:
        return _emit_failure(
            args,
            code="focus_measure_failed",
            message=f"Focus measurement failed: {exc}",
        )

    data = asdict(result)
    if not result.valid:
        return _emit_failure(
            args,
            code="focus_measurement_invalid",
            message=result.message or "Focus measurement is invalid",
            data=data,
        )

    if getattr(args, "json", False):
        payload = _json_envelope(
            command="focus.measure",
            ok=True,
            data=data,
            error=None,
        )
        print(json.dumps(payload, indent=2))
    else:
        print(f"HFR: {result.hfr_px:.2f} px")
        print(
            f"Stars: {result.star_count} accepted, "
            f"{result.rejected_star_count} rejected"
        )
        print(f"Scatter: {result.hfr_mad_px:.2f} px (MAD)")
    return 0
