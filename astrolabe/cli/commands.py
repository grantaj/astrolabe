import datetime
import os
import socket
import sys
import math
import logging
from pathlib import Path
import shutil

from astrolabe.config import load_config
from astrolabe.solver import get_solver_backend
from astrolabe.camera import get_camera_backend
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


def _init_logging(level: str | None) -> None:
    if not level:
        return
    level_map = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warn": logging.WARNING,
        "error": logging.ERROR,
    }
    logging.basicConfig(level=level_map.get(level, logging.INFO))


def _config_path_from_args(args) -> Path | None:
    if args is None:
        return None
    path = getattr(args, "config", None)
    return Path(path) if path else None


def run_doctor(args=None) -> int:
    _init_logging(getattr(args, "log_level", None))
    config = load_config(_config_path_from_args(args))
    if getattr(args, "dry_run", False):
        print("--dry-run has no effect for doctor.", file=sys.stderr)
    solver_backend = get_solver_backend(config)

    def check_indi_server():
        try:
            with socket.create_connection((config.indi_host, config.indi_port), timeout=2):
                return {"ok": True, "detail": "reachable"}
        except (ConnectionRefusedError, socket.timeout, OSError):
            return {"ok": False, "detail": "not reachable"}

    def check_solver():
        return solver_backend.is_available()

    def check_camera():
        try:
            camera = get_camera_backend(config)
        except Exception as e:
            return {"ok": False, "detail": f"invalid camera config: {e}"}
        try:
            camera.connect()
        except Exception as e:
            return {"ok": False, "detail": f"connect failed: {e}"}
        finally:
            try:
                camera.disconnect()
            except Exception:
                pass
        return {"ok": True, "detail": "connected"}

    def check_config():
        try:
            load_config(_config_path_from_args(args))
            return {"ok": True, "detail": "loaded (defaults applied if missing)"}
        except Exception as e:
            return {"ok": False, "detail": f"invalid config: {e}"}

    checks = {
        "config": check_config(),
        "indi_server": check_indi_server(),
        f"solver ({config.solver_name})": check_solver(),
        f"camera ({config.camera_backend})": check_camera(),
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
    _init_logging(getattr(args, "log_level", None))
    config = load_config(_config_path_from_args(args))

    if getattr(args, "dry_run", False):
        print("--dry-run has no effect for solve.", file=sys.stderr)
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

    extra_options = None
    if hasattr(args, "verbose") and args.verbose:
        extra_options = {"verbose": True}

    request = SolveRequest(
        image=image,
        search_radius_rad=search_radius_rad,
        timeout_s=getattr(args, "timeout", None),
        extra_options=extra_options,
    )
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
            details = None
            if getattr(args, "verbose", False) and result.raw_output:
                details = {"raw_output": result.raw_output}
            payload = _json_envelope(
                command="solve",
                ok=False,
                data=None,
                error={
                    "code": "solve_failed",
                    "message": result.message or "solve failed",
                    "details": details,
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
        if not result.success and getattr(args, "verbose", False) and result.raw_output:
            print("\n--- ASTAP output ---")
            print(result.raw_output)
    if not result.success:
        return 1
    return 0


def _parse_roi(value: str | None) -> tuple[int, int, int, int] | None:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != 4:
        raise ValueError("ROI must be in x,y,w,h format")
    return tuple(int(p) for p in parts)  # type: ignore[return-value]


def run_capture(args) -> int:
    _init_logging(getattr(args, "log_level", None))
    config = load_config(_config_path_from_args(args))
    if getattr(args, "dry_run", False):
        print("--dry-run has no effect for capture.", file=sys.stderr)

    exposure = args.exposure if args.exposure is not None else config.camera_default_exposure_s
    if exposure is None:
        print("Exposure is required (use --exposure or set camera.default_exposure_s).", file=sys.stderr)
        return 2

    try:
        roi = _parse_roi(args.roi)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    camera = get_camera_backend(config)
    image = camera.capture(
        exposure_s=exposure,
        gain=args.gain,
        binning=args.binning,
        roi=roi,
    )

    saved_path = None
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(image.data, (str, Path)):
            shutil.copy2(Path(image.data), out_path)
            saved_path = str(out_path)

    if args.json:
        import json

        payload = _json_envelope(
            command="capture",
            ok=True,
            data={
                "path": saved_path or image.data,
                "exposure_s": image.exposure_s,
                "timestamp_utc": image.timestamp_utc.isoformat(),
                "width_px": image.width_px,
                "height_px": image.height_px,
            },
            error=None,
        )
        print(json.dumps(payload, indent=2))
    else:
        print(f"Saved: {saved_path or image.data}")
        print(f"Exposure: {image.exposure_s}s")
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
    if getattr(args, "dry_run", False):
        print("--dry-run has no effect for view.", file=sys.stderr)

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
