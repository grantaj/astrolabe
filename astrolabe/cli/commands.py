import datetime
import os
import socket
import sys
import math

from astrolabe.config import load_config
from astrolabe.solver import get_solver_backend
from astrolabe.solver.types import Image, SolveRequest
from astrolabe.util.format import rad_to_hms, rad_to_dms, rad_to_deg


def _json_envelope(command: str, ok: bool, data=None, error=None) -> dict:
    return {
        "ok": ok,
        "command": command,
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "data": data,
        "error": error,
    }


def run_doctor(args=None) -> int:
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
            load_config()
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

    if args is not None and getattr(args, "json", False):
        import json

        payload = _json_envelope(
            command="doctor",
            ok=ok,
            data={"checks": checks},
            error=None if ok else {"code": "doctor_failed", "message": "one or more checks failed", "details": None},
        )
        print(json.dumps(payload, indent=2))
    else:
        print("Astrolabe Doctor Report")
        print("=======================")

        for name, result in checks.items():
            status = "OK" if result["ok"] else "MISSING"
            print(f"{name:20} : {status} ({result['detail']})")

        if ok:
            print("\nSystem ready.")
        else:
            print("\nSome components are missing or not configured.")

    return 0 if ok else 1


def run_solve(args) -> int:
    config = load_config()
    solver_backend = get_solver_backend(config)

    fits_path = args.input_fits_opt or args.input_fits
    if not fits_path:
        print("Input FITS file path is required.", file=sys.stderr)
        return 2
    if not os.path.isfile(fits_path):
        print(f"Input file not found: {fits_path}", file=sys.stderr)
        return 1

    image = Image(
        data=fits_path,
        width_px=0,  # Placeholder
        height_px=0,  # Placeholder
        timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
        exposure_s=0.0,  # Placeholder
        metadata={},
    )
    search_radius_deg = None
    if hasattr(args, "search_radius_deg") and args.search_radius_deg is not None:
        search_radius_deg = args.search_radius_deg
    elif config.solver_search_radius_deg is not None:
        search_radius_deg = config.solver_search_radius_deg

    search_radius_rad = None
    if search_radius_deg is not None:
        search_radius_rad = math.radians(search_radius_deg)

    request = SolveRequest(image=image, search_radius_rad=search_radius_rad)
    result = solver_backend.solve(request)
    if args.json:
        import json

        if result.success:
            payload = _json_envelope(
                command="solve",
                ok=True,
                data=result.__dict__,
                error=None,
            )
        else:
            payload = _json_envelope(
                command="solve",
                ok=False,
                data=None,
                error={
                    "code": "solve_failed",
                    "message": result.message or "solve failed",
                    "details": None,
                },
            )
        print(json.dumps(payload, indent=2))
    else:
        print(f"Success: {result.success}")
        if result.ra_rad is not None:
            print(f"RA: {rad_to_hms(result.ra_rad)}")
        else:
            print("RA: None")
        if result.dec_rad is not None:
            print(f"Dec: {rad_to_dms(result.dec_rad)}")
        else:
            print("Dec: None")
        print(f"Pixel scale: {result.pixel_scale_arcsec}")
        if result.rotation_rad is not None:
            print(f"Rotation: {rad_to_deg(result.rotation_rad):.3f}°")
        else:
            print("Rotation: None")
        print(f"RMS: {result.rms_arcsec}")
        print(f"Stars: {result.num_stars}")
        print(f"Message: {result.message}")
    if not result.success:
        return 1
    return 0


def run_view(args) -> int:
    try:
        from astropy.io import fits
    except ModuleNotFoundError:
        print(
            "astropy is required for 'astrolabe view'. Install with: pip install -e .[tools]",
            file=sys.stderr,
        )
        return 2

    fits_path = args.input_fits
    if not os.path.isfile(fits_path):
        print(f"Input file not found: {fits_path}", file=sys.stderr)
        return 1
    try:
        hdul = fits.open(fits_path)
        print("FITS Header:")
        print(hdul[0].header.tostring(sep="\n"))
        data = hdul[0].data
        if args.show:
            import matplotlib.pyplot as plt

            plt.imshow(data, cmap="gray", origin="lower")
            plt.title(f"{os.path.basename(fits_path)}")
            plt.colorbar()
            plt.show()
        hdul.close()
        return 0
    except Exception as e:
        print(f"Error viewing FITS file: {e}", file=sys.stderr)
        return 1
