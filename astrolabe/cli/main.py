import argparse
import sys
from datetime import datetime
import socket
from astrolabe import __version__
from astrolabe.config import load_config
from astrolabe.solver import get_solver_backend

def run_doctor():
    config = load_config()
    solver_backend = get_solver_backend(config)

    def check_indi_server():
        try:
            with socket.create_connection((config.indi_host, config.indi_port), timeout=2):
                return {"ok": True, "detail": "reachable"}
        except (ConnectionRefusedError, socket.timeout, OSError):
            return {"ok": False, "detail": "not reachable"}

    def check_solver():
        return solver_backend.is_available()

    def check_config():
        try:
            config = load_config()
            return {"ok": True, "detail": "loaded (defaults applied if missing)"}
        except Exception as e:
            return {"ok": False, "detail": f"invalid config: {e}"}


    checks = {
        "config": check_config(),
        "indi_server": check_indi_server(),
        f"solver ({config.solver_name})": check_solver(),
        "camera_backend": {"ok": False, "detail": "not implemented"},
        "mount_backend": {"ok": False, "detail": "not implemented"},
    }

    ok = all(c["ok"] for c in checks.values())

    print("Astrolabe Doctor Report")
    print("=======================")

    for name, result in checks.items():
        status = "OK" if result["ok"] else "MISSING"
        print(f"{name:20} : {status} ({result['detail']})")

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

    solve_parser = subparsers.add_parser("solve", help="Plate solve a FITS image")
    solve_parser.add_argument("--in", dest="input_fits", required=True, help="Input FITS file path")
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
        return run_doctor()

    if args.command == "solve":
        return run_solve(args)

    if args.command == "view":
        return run_view(args)

    parser.print_help()
    return 0


def run_solve(args):
    from astrolabe.solver.types import Image, SolveRequest
    import datetime
    import os
    config = load_config()
    solver_backend = get_solver_backend(config)

    # For now, just use file path as image data
    fits_path = args.input_fits
    if not os.path.isfile(fits_path):
        print(f"Input file not found: {fits_path}", file=sys.stderr)
        return 1

    # TODO: Read FITS header for width/height/exposure if needed
    image = Image(
        data=fits_path,
        width_px=0,  # Placeholder
        height_px=0,  # Placeholder
        timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
        exposure_s=0.0,  # Placeholder
        metadata={}
    )
    request = SolveRequest(image=image)
    result = solver_backend.solve(request)
    if args.json:
        import json
        print(json.dumps(result.__dict__, indent=2))
    else:
        print(f"Success: {result.success}")
        print(f"RA: {result.ra_rad}")
        print(f"Dec: {result.dec_rad}")
        print(f"Pixel scale: {result.pixel_scale_arcsec}")
        print(f"Rotation: {result.rotation_rad}")
        print(f"RMS: {result.rms_arcsec}")
        print(f"Stars: {result.num_stars}")
        print(f"Message: {result.message}")
    return 0


def run_view(args):
    from astropy.io import fits
    import os
    fits_path = args.input_fits
    if not os.path.isfile(fits_path):
        print(f"Input file not found: {fits_path}", file=sys.stderr)
        return 1
    try:
        hdul = fits.open(fits_path)
        print("FITS Header:")
        print(hdul[0].header.tostring(sep='\n'))
        data = hdul[0].data
        if args.show:
            import matplotlib.pyplot as plt
            plt.imshow(data, cmap='gray', origin='lower')
            plt.title(f"{os.path.basename(fits_path)}")
            plt.colorbar()
            plt.show()
        hdul.close()
        return 0
    except Exception as e:
        print(f"Error viewing FITS file: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
