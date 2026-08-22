import argparse
import sys
from astrolabe import __version__
from astrolabe.services.polar import MIN_POSES as _POLAR_MIN_POSES
from astrolabe.cli.commands import (
    run_doctor,
    run_solve,
    run_view,
    run_capture,
    run_mount,
    run_goto,
    run_resolve,
    run_align,
    run_polar,
    run_guide,
    run_plan,
    run_update,
)
from astrolabe.cli.focus import run_focus
from astrolabe.cli.runtime import handle_error
from astrolabe.errors import AstrolabeError


def _error_command(args) -> str:
    command = getattr(args, "command", None)
    if command == "mount":
        return f"mount.{args.action}"
    if command in {"pointing", "align"}:
        return f"{command}.{args.mode}"
    if command == "focus":
        return f"focus.{args.action}"
    if command == "guide":
        action = getattr(args, "action", None)
        return f"guide.{action}" if action else "guide"
    if command == "update":
        dataset = getattr(args, "dataset", None)
        return f"update.{dataset}" if dataset else "update"
    return command or "astrolabe"


def _dispatch(args, handler) -> int:
    """Run one CLI handler with a final Astrolabe-error boundary.

    Handlers retain their explicit local mappings where behavior differs, while
    this boundary also covers setup, backend wiring, and service construction.
    Non-Astrolabe exceptions deliberately continue to propagate unchanged.
    """
    try:
        return handler(args)
    except AstrolabeError as exc:
        return handle_error(args, _error_command(args), exc)


def main():
    parser = argparse.ArgumentParser(prog="astrolabe")
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    parser.add_argument("--config", help="Path to config file")
    parser.add_argument("--json", action="store_true", help="Output result as JSON")
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warn", "error"],
        help="Logging level",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        help="Operation timeout in seconds (best-effort)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not move mount; simulate actions where possible",
    )

    subparsers = parser.add_subparsers(dest="command")

    doctor_parser = subparsers.add_parser("doctor", help="Run system diagnostics")

    solve_parser = subparsers.add_parser("solve", help="Plate solve a FITS image")
    solve_parser.add_argument("input_fits", nargs="?", help="Input FITS file path")
    solve_parser.add_argument(
        "--in", dest="input_fits_opt", help="Input FITS file path"
    )
    solve_parser.add_argument(
        "--search-radius-deg",
        type=float,
        help="Search radius in degrees (overrides config)",
    )
    solve_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include solver output on failure",
    )

    capture_parser = subparsers.add_parser(
        "capture", help="Capture a FITS image from camera"
    )
    capture_parser.add_argument(
        "--exposure", type=float, help="Exposure time in seconds"
    )
    capture_parser.add_argument("--gain", type=float, help="Camera gain")
    capture_parser.add_argument(
        "--bin", dest="binning", type=int, help="Binning factor"
    )
    capture_parser.add_argument("--roi", type=str, help="ROI as x,y,w,h")
    capture_parser.add_argument("--out", type=str, help="Save image to path")
    # Future: add more arguments for hints

    view_parser = subparsers.add_parser("view", help="View FITS header and image")
    view_parser.add_argument(
        "--in", dest="input_fits", required=True, help="Input FITS file path"
    )
    view_parser.add_argument(
        "--show", action="store_true", help="Display image window (requires matplotlib)"
    )

    mount_parser = subparsers.add_parser("mount", help="Mount control and status")
    mount_subparsers = mount_parser.add_subparsers(dest="action", required=True)

    mount_status = mount_subparsers.add_parser("status", help="Show mount status")

    mount_slew = mount_subparsers.add_parser("slew", help="Slew mount to coordinates")
    mount_slew.add_argument(
        "--ra-deg", type=float, required=True, help="Right ascension in degrees"
    )
    mount_slew.add_argument(
        "--dec-deg", type=float, required=True, help="Declination in degrees"
    )

    mount_track = mount_subparsers.add_parser(
        "track", help="Enable or disable sidereal tracking"
    )
    mount_track_group = mount_track.add_mutually_exclusive_group(required=True)
    mount_track_group.add_argument(
        "--on", dest="tracking_enabled", action="store_true", help="Enable tracking"
    )
    mount_track_group.add_argument(
        "--off", dest="tracking_enabled", action="store_false", help="Disable tracking"
    )

    mount_park = mount_subparsers.add_parser("park", help="Park the mount")

    mount_stop = mount_subparsers.add_parser("stop", help="Stop mount motion")

    resolve_parser = subparsers.add_parser(
        "resolve", help="Resolve a target name or catalog ID"
    )
    resolve_parser.add_argument(
        "target",
        nargs="+",
        help="Target name or catalog ID (e.g., M31, NGC1976, Sirius)",
    )
    resolve_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of matches to return",
    )
    resolve_parser.add_argument(
        "--min-score",
        type=float,
        help="Minimum match score override (default from config)",
    )

    goto_parser = subparsers.add_parser(
        "goto", help="(deprecated) Alias for `pointing goto`"
    )
    goto_parser.add_argument(
        "--target",
        type=str,
        help="Target name or catalog ID (e.g., M31, NGC1976, Sirius)",
    )
    goto_parser.add_argument(
        "--ra-deg", type=float, help="Target right ascension in degrees"
    )
    goto_parser.add_argument(
        "--dec-deg", type=float, help="Target declination in degrees"
    )
    goto_parser.add_argument("--exposure", type=float, help="Exposure time in seconds")
    goto_parser.add_argument(
        "--tolerance-arcsec",
        type=float,
        default=None,
        help=argparse.SUPPRESS,
    )
    goto_parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )

    def _add_pointing_subcommands(pointing_subparsers):
        solve = pointing_subparsers.add_parser("solve", help="Solve current pointing")
        solve.add_argument("--exposure", type=float, help="Exposure time in seconds")

        goto = pointing_subparsers.add_parser(
            "goto", help="Apply model, slew, solve, and learn the pointing residual"
        )
        goto.add_argument(
            "--target",
            type=str,
            help="Target name or catalog ID (e.g., M31, NGC1976, Sirius)",
        )
        goto.add_argument("--ra-deg", type=float, help="Target RA in degrees")
        goto.add_argument("--dec-deg", type=float, help="Target Dec in degrees")
        goto.add_argument("--exposure", type=float, help="Exposure time in seconds")

    pointing_parser = subparsers.add_parser(
        "pointing", help="Solve-assisted pointing and continuous model learning"
    )
    pointing_subparsers = pointing_parser.add_subparsers(dest="mode", required=True)
    _add_pointing_subcommands(pointing_subparsers)

    align_parser = subparsers.add_parser("align", help="(deprecated) Use `pointing`")
    align_subparsers = align_parser.add_subparsers(dest="mode", required=True)
    _add_pointing_subcommands(align_subparsers)

    polar_parser = subparsers.add_parser("polar", help="Polar alignment routine")
    polar_parser.add_argument(
        "--ra-rotation-deg", type=float, required=True, help="RA rotation in degrees"
    )
    polar_parser.add_argument(
        "--latitude-deg",
        type=float,
        required=True,
        help="Observer latitude in degrees (positive north)",
    )
    polar_parser.add_argument(
        "--exposure",
        type=float,
        default=2.0,
        help="Exposure time in seconds (default: 2.0)",
    )
    polar_parser.add_argument(
        "--settle-time",
        type=float,
        default=2.0,
        help="Settle time after slew in seconds (default: 2.0)",
    )

    def _num_poses(value: str) -> int:
        n = int(value)
        if n < _POLAR_MIN_POSES:
            raise argparse.ArgumentTypeError(
                f"--num-poses must be ≥{_POLAR_MIN_POSES}, got {n}"
            )
        return n

    polar_parser.add_argument(
        "--num-poses",
        type=_num_poses,
        default=_POLAR_MIN_POSES,
        help=f"Number of capture/solve poses "
        f"(default: {_POLAR_MIN_POSES}, minimum: {_POLAR_MIN_POSES})",
    )

    focus_parser = subparsers.add_parser("focus", help="Measure focus quality")
    focus_subparsers = focus_parser.add_subparsers(dest="action", required=True)

    def _add_focus_frame_args(focus_command):
        focus_command.add_argument(
            "--exposure", type=float, help="Exposure time when capturing from camera"
        )
        focus_command.add_argument("--gain", type=float, help="Camera gain")
        focus_command.add_argument(
            "--bin", dest="binning", type=int, help="Binning factor"
        )
        focus_command.add_argument("--roi", help="ROI as x,y,w,h")
        focus_command.add_argument(
            "--min-stars",
            type=int,
            default=3,
            help="Minimum usable stars required (default: 3)",
        )
        focus_command.add_argument(
            "--detection-sigma",
            type=float,
            default=5.0,
            help="Detection threshold above background noise (default: 5.0)",
        )
        focus_command.add_argument(
            "--saturation-level",
            type=float,
            help="Explicit sensor saturation level; normally inferred from FITS",
        )

    focus_measure = focus_subparsers.add_parser(
        "measure", help="Measure multi-star half-flux radius once"
    )
    focus_measure.add_argument("--in", dest="input_fits", help="Input FITS file")
    _add_focus_frame_args(focus_measure)

    focus_monitor = focus_subparsers.add_parser(
        "monitor", help="Continuously report live focus quality"
    )
    _add_focus_frame_args(focus_monitor)
    focus_monitor.add_argument(
        "--frames",
        type=int,
        help="Stop after N frames instead of running until interrupted",
    )

    guide_parser = subparsers.add_parser("guide", help="Guiding control")
    guide_subparsers = guide_parser.add_subparsers(dest="action", required=True)

    guide_calibrate = guide_subparsers.add_parser("calibrate", help="Calibrate guiding")
    guide_calibrate.add_argument(
        "--duration", type=float, required=True, help="Calibration duration in seconds"
    )

    guide_start = guide_subparsers.add_parser("start", help="Start guiding")
    guide_start.add_argument(
        "--aggression", type=float, required=True, help="Aggression (0-1)"
    )
    guide_start.add_argument(
        "--min-move-arcsec", type=float, required=True, help="Minimum move arcsec"
    )

    guide_stop = guide_subparsers.add_parser("stop", help="Stop guiding")

    guide_status = guide_subparsers.add_parser("status", help="Guiding status")

    update_parser = subparsers.add_parser("update", help="Update optional datasets")
    update_subparsers = update_parser.add_subparsers(dest="dataset", required=True)

    update_catalog = update_subparsers.add_parser(
        "catalog", help="Update catalogs (OpenNGC + Hipparcos)"
    )
    catalog_subparsers = update_catalog.add_subparsers(dest="catalog_dataset")

    update_openngc = catalog_subparsers.add_parser(
        "openngc", help="Update curated OpenNGC catalog only"
    )
    update_openngc.add_argument("--source", help="OpenNGC CSV file or base URL/path")
    update_openngc.add_argument("--version", help="OpenNGC release tag or commit hash")
    update_openngc.add_argument("--output", help="Output path for curated catalog CSV")

    update_hip = catalog_subparsers.add_parser(
        "hip", help="Update Hipparcos star subset only"
    )
    update_hip.add_argument(
        "--source", help="Hipparcos catalog source URL or local path"
    )
    update_hip.add_argument("--output", help="Output path for hip_subset.csv")
    update_hip.add_argument(
        "--max-mag", type=float, help="Maximum V magnitude to include"
    )
    update_hip.add_argument(
        "--insecure",
        action="store_true",
        help="Disable SSL certificate verification (not recommended)",
    )

    update_bsc = catalog_subparsers.add_parser(
        "bsc", help="Update Bright Star Catalog crosswalk only"
    )
    update_bsc.add_argument("--source", help="BSC catalog source URL or local path")
    update_bsc.add_argument("--output", help="Output path for bsc_crosswalk.csv")
    update_bsc.add_argument(
        "--insecure",
        action="store_true",
        help="Disable SSL certificate verification (not recommended)",
    )

    plan_parser = subparsers.add_parser("plan", help="Plan observing targets")
    plan_parser.add_argument(
        "--start-utc", dest="window_start_utc", help="Window start (ISO-8601)"
    )
    plan_parser.add_argument(
        "--end-utc", dest="window_end_utc", help="Window end (ISO-8601)"
    )
    plan_parser.add_argument(
        "--start-local",
        dest="window_start_local",
        help="Window start (local time ISO-8601)",
    )
    plan_parser.add_argument(
        "--end-local", dest="window_end_local", help="Window end (local time ISO-8601)"
    )
    plan_parser.add_argument(
        "--mode", choices=["visual", "photo"], help="Planning mode"
    )
    plan_parser.add_argument("--limit", type=int, help="Limit total number of targets")
    plan_parser.add_argument(
        "--verbose", action="store_true", help="Include detailed numeric output"
    )
    plan_parser.add_argument(
        "--lat", dest="latitude_deg", type=float, help="Observer latitude degrees"
    )
    plan_parser.add_argument(
        "--lon", dest="longitude_deg", type=float, help="Observer longitude degrees"
    )
    plan_parser.add_argument(
        "--elev", dest="elevation_m", type=float, help="Observer elevation meters"
    )

    args = parser.parse_args()

    if args.version:
        print(f"Astrolabe {__version__}")
        return 0

    if args.command == "doctor":
        return _dispatch(args, run_doctor)

    if args.command == "solve":
        return _dispatch(args, run_solve)

    if args.command == "capture":
        return _dispatch(args, run_capture)

    if args.command == "view":
        return _dispatch(args, run_view)

    if args.command == "mount":
        return _dispatch(args, run_mount)

    if args.command == "resolve":
        return _dispatch(args, run_resolve)

    if args.command == "goto":
        return _dispatch(args, run_goto)

    if args.command == "pointing":
        return _dispatch(args, run_align)

    if args.command == "align":
        return _dispatch(args, run_align)

    if args.command == "polar":
        return _dispatch(args, run_polar)

    if args.command == "focus":
        return _dispatch(args, run_focus)

    if args.command == "guide":
        return _dispatch(args, run_guide)

    if args.command == "update":
        return _dispatch(args, run_update)

    if args.command == "plan":
        return _dispatch(args, run_plan)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())