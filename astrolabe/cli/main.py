import argparse
import sys
from datetime import datetime
from astrolabe import __version__


def run_doctor():
    checks = {
        "config": True,          # Placeholder
        "indi_server": False,    # Placeholder
        "camera_backend": False, # Placeholder
        "mount_backend": False   # Placeholder
    }

    ok = all(checks.values())

    print("Astrolabe Doctor Report")
    print("=======================")
    for k, v in checks.items():
        status = "OK" if v else "MISSING"
        print(f"{k:20} : {status}")

    if ok:
        print("\nSystem ready.")
        return 0
    else:
        print("\nSome components are missing or not configured.")
        return 1


def main():
    parser = argparse.ArgumentParser(prog="astrolabe")
    parser.add_argument("--version", action="store_true", help="Show version and exit")

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("doctor", help="Run system diagnostics")

    args = parser.parse_args()

    if args.version:
        print(f"Astrolabe {__version__}")
        return 0

    if args.command == "doctor":
        return run_doctor()

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
