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
from astrolabe.mount import get_mount_backend
from astrolabe.services import (
    GotoService,
    PolarAlignService,
    GuidingService,
    AlignmentService,
)
from astrolabe.planner import Planner, ObserverLocation
from astrolabe.planner.formatters import format_json as format_plan_json
from astrolabe.errors import NotImplementedFeature
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


def _handle_not_implemented(command: str, args, exc: NotImplementedFeature) -> int:
    if args is not None and getattr(args, "json", False):
        import json

        payload = _json_envelope(
            command=command,
            ok=False,
            data=None,
            error={
                "code": "not_implemented",
                "message": str(exc),
                "details": None,
            },
        )
        print(json.dumps(payload, indent=2))
    else:
        print(str(exc), file=sys.stderr)
    return 2


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
            with socket.create_connection(
                (config.indi_host, config.indi_port), timeout=2
            ):
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
            error=None
            if ok
            else {
                "code": "doctor_failed",
                "message": "one or more checks failed",
                "details": None,
            },
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


def _parse_datetime_arg(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _parse_location_args(args) -> ObserverLocation | None:
    lat = getattr(args, "latitude_deg", None)
    lon = getattr(args, "longitude_deg", None)
    elev = getattr(args, "elevation_m", None)
    if lat is None and lon is None and elev is None:
        return None
    if lat is None or lon is None:
        raise ValueError(
            "Both latitude and longitude are required when specifying location"
        )
    return ObserverLocation(latitude_deg=lat, longitude_deg=lon, elevation_m=elev)


def run_capture(args) -> int:
    _init_logging(getattr(args, "log_level", None))
    config = load_config(_config_path_from_args(args))
    if getattr(args, "dry_run", False):
        print("--dry-run has no effect for capture.", file=sys.stderr)

    exposure = (
        args.exposure if args.exposure is not None else config.camera_default_exposure_s
    )
    if exposure is None:
        print(
            "Exposure is required (use --exposure or set camera.default_exposure_s).",
            file=sys.stderr,
        )
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
                "path": str(saved_path or image.data),
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
        message = "astropy is required for 'astrolabe view'. Install with: uv pip install -e .[tools]"
        if getattr(args, "json", False):
            import json

            payload = _json_envelope(
                command="view",
                ok=False,
                data=None,
                error={
                    "code": "dependency_missing",
                    "message": message,
                    "details": None,
                },
            )
            print(json.dumps(payload, indent=2))
        else:
            print(message, file=sys.stderr)
        return 2
    if getattr(args, "dry_run", False):
        print("--dry-run has no effect for view.", file=sys.stderr)

    fits_path = args.input_fits
    if not os.path.isfile(fits_path):
        message = f"Input file not found: {fits_path}"
        if getattr(args, "json", False):
            import json

            payload = _json_envelope(
                command="view",
                ok=False,
                data=None,
                error={"code": "file_not_found", "message": message, "details": None},
            )
            print(json.dumps(payload, indent=2))
        else:
            print(message, file=sys.stderr)
        return 1
    try:
        hdul = fits.open(fits_path)
        header_text = hdul[0].header.tostring(sep="\n")
        data = hdul[0].data
        if args.show:
            import matplotlib.pyplot as plt

            plt.imshow(data, cmap="gray", origin="lower")
            plt.title(f"{os.path.basename(fits_path)}")
            plt.colorbar()
            plt.show()
        hdul.close()
        if getattr(args, "json", False):
            import json

            payload = _json_envelope(
                command="view",
                ok=True,
                data={"path": fits_path, "header": header_text, "show": args.show},
                error=None,
            )
            print(json.dumps(payload, indent=2))
        else:
            print("FITS Header:")
            print(header_text)
        return 0
    except Exception as e:
        message = f"Error viewing FITS file: {e}"
        if getattr(args, "json", False):
            import json

            payload = _json_envelope(
                command="view",
                ok=False,
                data=None,
                error={"code": "view_failed", "message": message, "details": None},
            )
            print(json.dumps(payload, indent=2))
        else:
            print(message, file=sys.stderr)
        return 1


def run_mount(args) -> int:
    _init_logging(getattr(args, "log_level", None))
    config = load_config(_config_path_from_args(args))
    mount = get_mount_backend(config)
    if getattr(args, "dry_run", False):
        print("--dry-run has no effect for mount.", file=sys.stderr)

    try:
        if args.action == "status":
            state = mount.get_state()
            if getattr(args, "json", False):
                import json

                payload = _json_envelope(
                    command=f"mount.{args.action}",
                    ok=True,
                    data={
                        "connected": state.connected,
                        "tracking": state.tracking,
                        "slewing": state.slewing,
                        "ra_rad": state.ra_rad,
                        "dec_rad": state.dec_rad,
                        "timestamp_utc": state.timestamp_utc.isoformat()
                        if state.timestamp_utc
                        else None,
                    },
                    error=None,
                )
                print(json.dumps(payload, indent=2))
            else:
                print(f"Connected: {state.connected}")
                print(f"Tracking: {state.tracking}")
                print(f"Slewing: {state.slewing}")
                print(f"RA (rad): {state.ra_rad}")
                print(f"Dec (rad): {state.dec_rad}")
                print(f"Timestamp: {state.timestamp_utc.isoformat()}")
            return 0

        if args.action == "slew":
            ra_rad = math.radians(args.ra_deg)
            dec_rad = math.radians(args.dec_deg)
            mount.slew_to(ra_rad=ra_rad, dec_rad=dec_rad)
            if getattr(args, "json", False):
                import json

                payload = _json_envelope(
                    command="mount.slew",
                    ok=True,
                    data=None,
                    error=None,
                )
                print(json.dumps(payload, indent=2))
            return 0

        if args.action == "park":
            mount.park()
            if getattr(args, "json", False):
                import json

                payload = _json_envelope(
                    command="mount.park",
                    ok=True,
                    data=None,
                    error=None,
                )
                print(json.dumps(payload, indent=2))
            return 0

        if args.action == "stop":
            mount.stop()
            if getattr(args, "json", False):
                import json

                payload = _json_envelope(
                    command="mount.stop",
                    ok=True,
                    data=None,
                    error=None,
                )
                print(json.dumps(payload, indent=2))
            return 0

        print("Unknown mount action.", file=sys.stderr)
        return 2
    except NotImplementedFeature as e:
        return _handle_not_implemented(f"mount.{args.action}", args, e)


def run_goto(args) -> int:
    _init_logging(getattr(args, "log_level", None))
    config = load_config(_config_path_from_args(args))
    mount = get_mount_backend(config)
    camera = get_camera_backend(config)
    solver = get_solver_backend(config)
    if getattr(args, "dry_run", False):
        print("--dry-run has no effect for goto.", file=sys.stderr)
    service = GotoService(mount, camera, solver)

    try:
        result = service.center_target(
            target_ra_rad=math.radians(args.ra_deg),
            target_dec_rad=math.radians(args.dec_deg),
            tolerance_arcsec=args.tolerance_arcsec,
            max_iterations=args.max_iterations,
        )
        if getattr(args, "json", False):
            import json

            payload = _json_envelope(
                command="goto",
                ok=result.success,
                data=result.__dict__,
                error=None
                if result.success
                else {
                    "code": "goto_failed",
                    "message": result.message or "goto failed",
                    "details": None,
                },
            )
            print(json.dumps(payload, indent=2))
        else:
            print(f"Success: {result.success}")
            print(f"Final error: {result.final_error_arcsec}")
            print(f"Iterations: {result.iterations}")
            print(f"Message: {result.message}")
        return 0 if result.success else 1
    except NotImplementedFeature as e:
        return _handle_not_implemented("goto", args, e)


def run_align(args) -> int:
    _init_logging(getattr(args, "log_level", None))
    config = load_config(_config_path_from_args(args))
    mount = get_mount_backend(config)
    camera = get_camera_backend(config)
    solver = get_solver_backend(config)
    if getattr(args, "dry_run", False):
        print("--dry-run has no effect for align.", file=sys.stderr)
    service = AlignmentService(mount, camera, solver)

    try:
        if args.mode == "solve":
            result = service.solve_current(exposure_s=args.exposure)
            if getattr(args, "json", False):
                import json

                payload = _json_envelope(
                    command="align.solve",
                    ok=result.success,
                    data=result.__dict__,
                    error=None
                    if result.success
                    else {
                        "code": "align_failed",
                        "message": result.message or "align solve failed",
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
            return 0 if result.success else 1
        if args.mode == "sync":
            result = service.sync_current(exposure_s=args.exposure)
        elif args.mode == "init":
            result = service.initial_alignment(
                target_count=args.target_count,
                exposure_s=args.exposure,
                max_attempts=args.max_attempts,
            )
        else:
            print("Unknown alignment mode.", file=sys.stderr)
            return 2

        if getattr(args, "json", False):
            import json

            payload = _json_envelope(
                command=f"align.{args.mode}",
                ok=result.success,
                data=result.__dict__,
                error=None
                if result.success
                else {
                    "code": "align_failed",
                    "message": result.message or f"align {args.mode} failed",
                    "details": None,
                },
            )
            print(json.dumps(payload, indent=2))
        else:
            print(f"Success: {result.success}")
            print(f"Solves attempted: {result.solves_attempted}")
            print(f"Solves succeeded: {result.solves_succeeded}")
            print(f"RMS (arcsec): {result.rms_arcsec}")
            print(f"Message: {result.message}")
        return 0 if result.success else 1
    except NotImplementedFeature as e:
        return _handle_not_implemented(f"align.{args.mode}", args, e)


def run_polar(args) -> int:
    _init_logging(getattr(args, "log_level", None))
    config = load_config(_config_path_from_args(args))
    mount = get_mount_backend(config)
    camera = get_camera_backend(config)
    solver = get_solver_backend(config)
    if getattr(args, "dry_run", False):
        print("--dry-run has no effect for polar.", file=sys.stderr)
    service = PolarAlignService(mount, camera, solver)

    try:
        result = service.run(ra_rotation_rad=math.radians(args.ra_rotation_deg))
        if getattr(args, "json", False):
            import json

            payload = _json_envelope(
                command="polar",
                ok=True,
                data=result.__dict__,
                error=None,
            )
            print(json.dumps(payload, indent=2))
        else:
            print(f"Altitude correction (arcsec): {result.alt_correction_arcsec}")
            print(f"Azimuth correction (arcsec): {result.az_correction_arcsec}")
            print(f"Residual (arcsec): {result.residual_arcsec}")
            print(f"Confidence: {result.confidence}")
            print(f"Message: {result.message}")
        return 0
    except NotImplementedFeature as e:
        return _handle_not_implemented("polar", args, e)


def run_guide(args) -> int:
    _init_logging(getattr(args, "log_level", None))
    config = load_config(_config_path_from_args(args))
    mount = get_mount_backend(config)
    camera = get_camera_backend(config)
    service = GuidingService(mount, camera)
    if getattr(args, "dry_run", False):
        print("--dry-run has no effect for guide.", file=sys.stderr)

    try:
        if args.action == "calibrate":
            result = service.calibrate(duration_s=args.duration)
            if getattr(args, "json", False):
                import json

                payload = _json_envelope(
                    command="guide",
                    ok=result.success,
                    data=result.__dict__,
                    error=None
                    if result.success
                    else {
                        "code": "guide_failed",
                        "message": result.message or "guide calibration failed",
                        "details": None,
                    },
                )
                print(json.dumps(payload, indent=2))
            else:
                print(f"Success: {result.success}")
                print(f"Message: {result.message}")
            return 0 if result.success else 1

        if args.action == "start":
            service.start(
                aggression=args.aggression, min_move_arcsec=args.min_move_arcsec
            )
            if getattr(args, "json", False):
                import json

                payload = _json_envelope(
                    command="guide.start",
                    ok=True,
                    data=None,
                    error=None,
                )
                print(json.dumps(payload, indent=2))
            return 0

        if args.action == "stop":
            service.stop()
            if getattr(args, "json", False):
                import json

                payload = _json_envelope(
                    command="guide.stop",
                    ok=True,
                    data=None,
                    error=None,
                )
                print(json.dumps(payload, indent=2))
            return 0

        if args.action == "status":
            status = service.status()
            if getattr(args, "json", False):
                import json

                payload = _json_envelope(
                    command="guide.status",
                    ok=True,
                    data=status.__dict__,
                    error=None,
                )
                print(json.dumps(payload, indent=2))
            else:
                print(f"Running: {status.running}")
                print(f"RMS (arcsec): {status.rms_arcsec}")
                print(f"Star lost: {status.star_lost}")
                print(f"Last error (arcsec): {status.last_error_arcsec}")
            return 0

        print("Unknown guiding action.", file=sys.stderr)
        return 2
    except NotImplementedFeature as e:
        action = getattr(args, "action", None)
        command = f"guide.{action}" if action else "guide"
        return _handle_not_implemented(command, args, e)


def run_plan(args) -> int:
    _init_logging(getattr(args, "log_level", None))
    config = load_config(_config_path_from_args(args))
    planner = Planner(config)
    if getattr(args, "dry_run", False):
        print("--dry-run has no effect for plan.", file=sys.stderr)

    try:
        window_start = _parse_datetime_arg(args.window_start_utc)
        window_end = _parse_datetime_arg(args.window_end_utc)
        location = _parse_location_args(args)
        result = planner.plan(
            window_start_utc=window_start,
            window_end_utc=window_end,
            location=location,
            constraints=None,
        )
        if getattr(args, "json", False):
            import json
            from dataclasses import asdict

            payload = _json_envelope(
                command="plan",
                ok=True,
                data=asdict(result),
                error=None,
            )
            print(json.dumps(payload, indent=2, default=str))
        else:
            print(format_plan_json(result))
        return 0
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    except NotImplementedFeature as e:
        return _handle_not_implemented("plan", args, e)
