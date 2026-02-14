import argparse
import sys
from astrolabe import __version__
from astrolabe.cli.commands import run_doctor, run_solve, run_view
def main():
    parser = argparse.ArgumentParser(prog="astrolabe")
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    parser.add_argument("--config", help="Path to config file")
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
    doctor_parser.add_argument("--json", action="store_true", help="Output result as JSON")

    solve_parser = subparsers.add_parser("solve", help="Plate solve a FITS image")
    solve_parser.add_argument("input_fits", nargs="?", help="Input FITS file path")
    solve_parser.add_argument("--in", dest="input_fits_opt", help="Input FITS file path")
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
    solve_parser.add_argument("--json", action="store_true", help="Output result as JSON")
    # Future: add more arguments for hints

    view_parser = subparsers.add_parser("view", help="View FITS header and image")
    view_parser.add_argument("--in", dest="input_fits", required=True, help="Input FITS file path")
    view_parser.add_argument("--show", action="store_true", help="Display image window (requires matplotlib)")

    args = parser.parse_args()

    if args.version:
        print(f"Astrolabe {__version__}")
        return 0

    if args.command == "doctor":
        return run_doctor(args)

    if args.command == "solve":
        return run_solve(args)

    if args.command == "view":
        return run_view(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
