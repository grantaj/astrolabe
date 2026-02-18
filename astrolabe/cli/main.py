import argparse
import sys
from astrolabe import __version__
from astrolabe.cli.commands import (
    run_doctor,
    run_solve,
    run_view,
    run_capture,
    run_mount,
    run_goto,
    run_align,
    run_polar,
    run_guide,
    run_plan,
)


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

    _ = subparsers.add_parser("doctor", help="Run system diagnostics")

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

    _ = mount_subparsers.add_parser("status", help="Show mount status")

    mount_slew = mount_subparsers.add_parser("slew", help="Slew mount to coordinates")
    mount_slew.add_argument(
        "--ra-deg", type=float, required=True, help="Right ascension in degrees"
    )
    mount_slew.add_argument(
        "--dec-deg", type=float, required=True, help="Declination in degrees"
    )

    _ = mount_subparsers.add_parser("park", help="Park the mount")

    _ = mount_subparsers.add_parser("stop", help="Stop mount motion")

    goto_parser = subparsers.add_parser("goto", help="Closed-loop goto centering")
    goto_parser.add_argument(
        "--ra-deg", type=float, required=True, help="Target right ascension in degrees"
    )
    goto_parser.add_argument(
        "--dec-deg", type=float, required=True, help="Target declination in degrees"
    )
    goto_parser.add_argument(
        "--tolerance-arcsec", type=float, default=30.0, help="Tolerance in arcseconds"
    )
    goto_parser.add_argument(
        "--max-iterations", type=int, default=5, help="Maximum iterations"
    )

    align_parser = subparsers.add_parser("align", help="Plate-solve alignment")
    align_subparsers = align_parser.add_subparsers(dest="mode", required=True)

    align_solve = align_subparsers.add_parser("solve", help="Solve current pointing")
    align_solve.add_argument("--exposure", type=float, help="Exposure time in seconds")

    align_sync = align_subparsers.add_parser(
        "sync", help="Solve and sync current pointing"
    )
    align_sync.add_argument("--exposure", type=float, help="Exposure time in seconds")

    align_init = align_subparsers.add_parser(
        "init", help="Initial multi-point alignment"
    )
    align_init.add_argument(
        "--targets", dest="target_count", type=int, default=3, help="Target count"
    )
    align_init.add_argument("--exposure", type=float, help="Exposure time in seconds")
    align_init.add_argument("--max-attempts", type=int, help="Max attempts")

    polar_parser = subparsers.add_parser("polar", help="Polar alignment routine")
    polar_parser.add_argument(
        "--ra-rotation-deg", type=float, required=True, help="RA rotation in degrees"
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

    _ = guide_subparsers.add_parser("stop", help="Stop guiding")

    _ = guide_subparsers.add_parser("status", help="Guiding status")

    plan_parser = subparsers.add_parser("plan", help="Plan observing targets")
    plan_parser.add_argument(
        "--start-utc", dest="window_start_utc", help="Window start (ISO-8601)"
    )
    plan_parser.add_argument(
        "--end-utc", dest="window_end_utc", help="Window end (ISO-8601)"
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
        return run_doctor(args)

    if args.command == "solve":
        return run_solve(args)

    if args.command == "capture":
        return run_capture(args)

    if args.command == "view":
        return run_view(args)

    if args.command == "mount":
        return run_mount(args)

    if args.command == "goto":
        return run_goto(args)

    if args.command == "align":
        return run_align(args)

    if args.command == "polar":
        return run_polar(args)

    if args.command == "guide":
        return run_guide(args)

    if args.command == "plan":
        return run_plan(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
