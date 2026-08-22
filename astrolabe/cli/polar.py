"""CLI boundary for one-shot and interactive polar alignment."""

from __future__ import annotations

import argparse
import math
from dataclasses import asdict, replace

from astrolabe.cli.commands import run_polar as run_polar_measure
from astrolabe.cli.output import emit, emit_error
from astrolabe.cli.runtime import (
    config_path,
    handle_error,
    mount_camera_solver,
    prepare,
)
from astrolabe.config import load_config
from astrolabe.errors import AstrolabeError
from astrolabe.services.feedback import FeedbackDirection
from astrolabe.services.polar import (
    MIN_POSES,
    PolarAdjustConfig,
    PolarAdjustmentUpdate,
    PolarAlignService,
    PolarAxis,
    PolarWorkflowState,
)


def configure_polar_parser(parser: argparse.ArgumentParser) -> None:
    """Configure the additive ``polar [measure|adjust]`` CLI surface."""
    parser.add_argument(
        "polar_action",
        nargs="?",
        choices=("measure", "adjust"),
        help="Measure only (default) or interactively adjust AZ then ALT",
    )
    parser.add_argument(
        "--ra-rotation-deg",
        type=float,
        required=True,
        help="RA rotation between measurement poses in degrees",
    )
    parser.add_argument(
        "--latitude-deg",
        type=float,
        help="Observer latitude; defaults to configured mount/site latitude",
    )
    parser.add_argument(
        "--longitude-deg",
        type=float,
        help="Observer longitude east-positive; required for adjust unless configured",
    )
    parser.add_argument(
        "--elevation-m",
        type=float,
        help="Observer elevation; defaults to configured site elevation or zero",
    )
    parser.add_argument(
        "--exposure",
        type=float,
        default=2.0,
        help="Exposure time in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--settle-time",
        type=float,
        default=2.0,
        help="Settle time after measurement slews in seconds (default: 2.0)",
    )

    def _num_poses(value: str) -> int:
        n = int(value)
        if n < MIN_POSES:
            raise argparse.ArgumentTypeError(
                f"--num-poses must be ≥{MIN_POSES}, got {n}"
            )
        return n

    parser.add_argument(
        "--num-poses",
        type=_num_poses,
        default=MIN_POSES,
        help=f"Number of measurement poses (default/minimum: {MIN_POSES})",
    )
    parser.add_argument(
        "--tolerance-arcsec",
        type=float,
        default=30.0,
        help="Interactive on-target tolerance in arcseconds (default: 30)",
    )
    parser.add_argument(
        "--stable-samples",
        type=int,
        default=3,
        help="Consecutive on-target solves required per axis (default: 3)",
    )


def run_polar(args) -> int:
    action = getattr(args, "polar_action", None) or "measure"
    if action == "measure":
        return _run_measure(args)
    return _run_adjust(args)


def _run_measure(args) -> int:
    if args.latitude_deg is None:
        config = load_config(config_path(args))
        args.latitude_deg = config.mount_site_latitude_deg
    if args.latitude_deg is None:
        return emit_error(
            args,
            "polar",
            code="site_location_required",
            message=(
                "polar measurement requires --latitude-deg or a configured "
                "mount/site latitude"
            ),
            exit_code=2,
        )
    return run_polar_measure(args)


def _run_adjust(args) -> int:
    if getattr(args, "json", False):
        return emit_error(
            args,
            "polar.adjust",
            code="interactive_json_unsupported",
            message=(
                "polar adjust is an interactive streaming workflow and does not "
                "support global --json"
            ),
            exit_code=2,
        )

    try:
        app_config = prepare(args, "polar adjust")
        latitude_deg = (
            args.latitude_deg
            if args.latitude_deg is not None
            else app_config.mount_site_latitude_deg
        )
        longitude_deg = (
            args.longitude_deg
            if args.longitude_deg is not None
            else app_config.mount_site_longitude_deg
        )
        elevation_m = (
            args.elevation_m
            if args.elevation_m is not None
            else app_config.mount_site_elevation_m
        )
        if latitude_deg is None or longitude_deg is None:
            return emit_error(
                args,
                "polar.adjust",
                code="site_location_required",
                message=(
                    "polar adjust requires latitude and longitude via CLI or "
                    "configured mount/site location"
                ),
                exit_code=2,
            )
        if elevation_m is None:
            elevation_m = 0.0
        if not math.isfinite(args.tolerance_arcsec) or args.tolerance_arcsec <= 0.0:
            return emit_error(
                args,
                "polar.adjust",
                code="invalid_argument",
                message="--tolerance-arcsec must be finite and > 0",
                exit_code=2,
            )
        if args.stable_samples < 2:
            return emit_error(
                args,
                "polar.adjust",
                code="invalid_argument",
                message="--stable-samples must be >= 2",
                exit_code=2,
            )

        base_config = PolarAdjustConfig()
        tolerance_rad = math.radians(args.tolerance_arcsec / 3600.0)
        feedback_config = replace(base_config.feedback, tolerance=tolerance_rad)
        adjust_config = replace(
            base_config,
            feedback=feedback_config,
            stable_samples=args.stable_samples,
        )

        mount, camera, solver = mount_camera_solver(app_config)
        service = PolarAlignService(mount, camera, solver)
        result = service.adjust(
            ra_rotation_rad=math.radians(args.ra_rotation_deg),
            site_latitude_rad=math.radians(latitude_deg),
            site_longitude_rad=math.radians(longitude_deg),
            site_elevation_m=elevation_m,
            exposure_s=args.exposure,
            settle_time_s=args.settle_time,
            num_poses=args.num_poses,
            config=adjust_config,
            on_update=_render_adjustment_update,
        )
    except AstrolabeError as exc:
        return handle_error(args, "polar.adjust", exc)
    except ValueError as exc:
        return emit_error(
            args,
            "polar.adjust",
            code="invalid_argument",
            message=str(exc),
            exit_code=2,
        )

    if result.success:
        emit(
            args,
            "polar.adjust",
            ok=True,
            data=asdict(result),
            human="Polar alignment complete; tracking restored.",
        )
        return 0

    message = result.message or "polar adjustment failed"
    emit(
        args,
        "polar.adjust",
        ok=False,
        data=asdict(result),
        error={"code": result.state.value, "message": message},
        human=f"Polar adjustment stopped: {message}",
    )
    return 1


def _render_adjustment_update(update: PolarAdjustmentUpdate) -> None:
    if update.state is PolarWorkflowState.PREPARE_ADJUSTMENT:
        print("Initial polar-axis measurement complete; tracking off for adjustment.")
        print("Adjust AZ only; leave altitude untouched.")
        return
    if update.state is PolarWorkflowState.REBASE_FOR_ALT:
        print("AZ accepted. Leave azimuth untouched; adjust ALT only.")
        return
    if update.state in {
        PolarWorkflowState.AZ_ON_TARGET,
        PolarWorkflowState.ALT_ON_TARGET,
    }:
        label = "AZ" if update.axis is PolarAxis.AZ else "ALT"
        print(f"{label} stable on target.")
        return
    if update.state not in {
        PolarWorkflowState.ADJUST_AZ,
        PolarWorkflowState.ADJUST_ALT,
    }:
        return

    label = "AZ" if update.axis is PolarAxis.AZ else "ALT"
    feedback = update.feedback
    if feedback is None or not feedback.valid:
        detail = update.message or "measurement unavailable"
        print(f"{label}: guidance unavailable ({detail})")
        return
    if feedback.direction is FeedbackDirection.CENTERED:
        print(f"{label}: on target — hold position")
        return
    if feedback.direction is FeedbackDirection.UNKNOWN or feedback.guidance is None:
        print(f"{label}: guidance unavailable")
        return

    if update.axis is PolarAxis.AZ:
        direction = (
            "east" if feedback.direction is FeedbackDirection.POSITIVE else "west"
        )
    else:
        direction = (
            "raise" if feedback.direction is FeedbackDirection.POSITIVE else "lower"
        )
    magnitude = _format_small_angle(abs(feedback.guidance))
    print(f"{label}: {direction} {magnitude}")


def _format_small_angle(angle_rad: float) -> str:
    arcsec = math.degrees(angle_rad) * 3600.0
    if arcsec >= 60.0:
        return f"{arcsec / 60.0:.1f} arcmin"
    return f"{arcsec:.0f} arcsec"
