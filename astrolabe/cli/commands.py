import datetime
from dataclasses import asdict
import os
import socket
import sys
import math
from pathlib import Path
import shutil

from astrolabe.config import load_config
from astrolabe.solver import get_solver_backend
from astrolabe.camera import get_camera_backend
from astrolabe.camera.pixels import (
    fits_header_text,
    load_fits_pixels,
    validate_fits_structure,
)
from astrolabe.mount import get_mount_backend
from astrolabe.cli.output import (
    emit,
    emit_error,
    emit_result,
    error_object,
    format_dec,
    format_ra,
    format_solve_summary,
)
from astrolabe.cli.runtime import (
    config_path,
    init_logging,
    handle_error,
    mount_camera_solver,
    note_dry_run,
    prepare,
)
from astrolabe.services import PolarAlignService, GuidingService
from astrolabe.pointing import (
    PointingModel,
    PointingService,
    default_model_path,
    load_pointing_model,
    save_pointing_model,
)
from astrolabe.planner import Planner, ObserverLocation
from astrolabe.planner.formatters import format_text as format_plan_text
from astrolabe.planner.update import update_catalog
from astrolabe.services.target.update import update_hipparcos, update_bsc_crosswalk
from astrolabe.errors import AstrolabeError
from astrolabe.services.polar import MIN_POSES as _POLAR_MIN_POSES
from astrolabe.solver.types import Image, SolveRequest


def _doctor_checks(args, config, solver_backend) -> dict:
    """Run the diagnostic probes. Each probe degrades to a not-ok report row
    rather than failing the command, except the solver probe, whose errors are
    the backend's own and belong in the shared error mapping."""

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

    def check_mount():
        try:
            mount = get_mount_backend(config)
        except Exception as e:
            return {"ok": False, "detail": f"invalid mount config: {e}"}
        try:
            mount.connect()
        except Exception as e:
            return {"ok": False, "detail": f"connect failed: {e}"}
        finally:
            try:
                mount.disconnect()
            except Exception:
                pass
        return {"ok": True, "detail": "connected"}

    def check_config():
        try:
            load_config(config_path(args))
            return {"ok": True, "detail": "loaded (defaults applied if missing)"}
        except Exception as e:
            return {"ok": False, "detail": f"invalid config: {e}"}

    return {
        "config": check_config(),
        "indi_server": check_indi_server(),
        f"solver ({config.solver_name})": check_solver(),
        f"camera ({config.camera_backend})": check_camera(),
        f"mount ({config.mount_backend})": check_mount(),
    }


def run_doctor(args=None) -> int:
    try:
        config = prepare(args, "doctor")
        solver_backend = get_solver_backend(config)
        checks = _doctor_checks(args, config, solver_backend)
    except AstrolabeError as exc:
        return handle_error(args, "doctor", exc)

    ok = all(c["ok"] for c in checks.values())

    report = ["Astrolabe Doctor Report", "======================="]
    report += [
        f"{name:20} : {'OK' if result['ok'] else 'MISSING'} ({result['detail']})"
        for name, result in checks.items()
    ]
    report += [
        "\nSystem ready." if ok else "\nSome components are missing or not configured."
    ]

    emit(
        args,
        "doctor",
        ok=ok,
        data={"checks": checks},
        error=None
        if ok
        else error_object("doctor_failed", "one or more checks failed"),
        human="\n".join(report),
    )
    return 0 if ok else 1


def run_solve(args) -> int:
    config = prepare(args, "solve")
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
        width_px=0,
        height_px=0,
        timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
        exposure_s=0.0,
        metadata={},
    )
    search_radius_deg = getattr(args, "search_radius_deg", None)
    if search_radius_deg is None:
        search_radius_deg = config.solver_search_radius_deg

    verbose = getattr(args, "verbose", False)
    request = SolveRequest(
        image=image,
        search_radius_rad=None
        if search_radius_deg is None
        else math.radians(search_radius_deg),
        timeout_s=getattr(args, "timeout", None),
        extra_options={"verbose": True} if verbose else None,
    )

    try:
        result = solver_backend.solve(request)
    except AstrolabeError as exc:
        return handle_error(args, "solve", exc)

    details = (
        {"raw_output": result.raw_output}
        if verbose and not result.success and result.raw_output
        else None
    )
    emit(
        args,
        "solve",
        ok=result.success,
        data=result.__dict__ if result.success else None,
        error=None
        if result.success
        else error_object("solve_failed", result.message or "solve failed", details),
        human=format_solve_summary(result, raw_output_on_failure=verbose),
    )
    return 0 if result.success else 1


def _parse_roi(value: str | None) -> tuple[int, int, int, int] | None:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != 4:
        raise ValueError("ROI must be in x,y,w,h format")
    x, y, w, h = (int(p) for p in parts)
    return (x, y, w, h)


def _parse_datetime_arg(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _parse_datetime_local_arg(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(value)
    if dt.tzinfo is None:
        local_tz = datetime.datetime.now().astimezone().tzinfo
        if local_tz is None:
            local_tz = datetime.timezone.utc
        dt = dt.replace(tzinfo=local_tz)
    return dt.astimezone(datetime.timezone.utc)


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
    config = prepare(args, "capture")

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

    try:
        camera = get_camera_backend(config)
        image = camera.capture(
            exposure_s=exposure,
            gain=args.gain,
            binning=args.binning,
            roi=roi,
        )
    except AstrolabeError as exc:
        return handle_error(args, "capture", exc)

    saved_path = None
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(image.data, (str, Path)):
            shutil.copy2(Path(image.data), out_path)
            saved_path = str(out_path)

    emit(
        args,
        "capture",
        ok=True,
        data={
            "path": str(saved_path or image.data),
            "exposure_s": image.exposure_s,
            "timestamp_utc": image.timestamp_utc.isoformat(),
            "width_px": image.width_px,
            "height_px": image.height_px,
        },
        human=f"Saved: {saved_path or image.data}\nExposure: {image.exposure_s}s",
    )
    return 0


def run_view(args) -> int:
    note_dry_run(args, "view")

    fits_path = args.input_fits
    if not os.path.isfile(fits_path):
        return emit_error(
            args,
            "view",
            code="file_not_found",
            message=f"Input file not found: {fits_path}",
        )
    try:
        # Structure is checked for every input; only --show needs decodable
        # pixels, so header inspection stays open to any valid primary HDU.
        validate_fits_structure(fits_path)
        header_text = fits_header_text(fits_path)
        if args.show:
            import matplotlib.pyplot as plt

            plt.imshow(load_fits_pixels(fits_path).pixels, cmap="gray", origin="lower")
            plt.title(f"{os.path.basename(fits_path)}")
            plt.colorbar()
            plt.show()
    except AstrolabeError as e:
        return handle_error(args, "view", e)
    except Exception as e:
        # FITS decode/matplotlib failures keep their own recoverable error code.
        return emit_error(
            args,
            "view",
            code="view_failed",
            message=f"Error viewing FITS file: {e}",
        )

    emit(
        args,
        "view",
        ok=True,
        data={"path": fits_path, "header": header_text, "show": args.show},
        human=f"FITS Header:\n{header_text}",
    )
    return 0


def run_mount(args) -> int:
    config = prepare(args)
    mount = get_mount_backend(config)
    note_dry_run(args, "mount")

    try:
        if args.action == "status":
            state = mount.get_state()
            emit(
                args,
                "mount.status",
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
                human="\n".join(
                    [
                        f"Connected: {state.connected}",
                        f"Tracking: {state.tracking}",
                        f"Slewing: {state.slewing}",
                        format_ra(state.ra_rad),
                        format_dec(state.dec_rad),
                        f"Timestamp: {state.timestamp_utc.isoformat()}",
                    ]
                ),
            )
            return 0

        if args.action == "slew":
            mount.slew_to(
                ra_rad=math.radians(args.ra_deg), dec_rad=math.radians(args.dec_deg)
            )
            emit(args, "mount.slew", ok=True)
            return 0

        if args.action == "park":
            mount.park()
            emit(args, "mount.park", ok=True)
            return 0

        if args.action == "stop":
            mount.stop()
            emit(args, "mount.stop", ok=True)
            return 0

        if args.action == "track":
            mount.set_tracking(args.tracking_enabled)
            label = "enabled" if args.tracking_enabled else "disabled"
            emit(
                args,
                "mount.track",
                ok=True,
                data={"tracking": args.tracking_enabled},
                human=f"Tracking {label}.",
            )
            return 0

        print("Unknown mount action.", file=sys.stderr)
        return 2
    except AstrolabeError as e:
        return handle_error(args, f"mount.{args.action}", e)


def run_goto(args) -> int:
    """Deprecated top-level spelling for the canonical Pointing goto operation."""
    args.mode = "goto"
    return run_align(args)


def run_resolve(args) -> int:
    config = prepare(args, "resolve")

    from astrolabe.services.target.resolver import TargetResolver

    query = " ".join(args.target).strip()
    if not query:
        print("resolve requires a target name or catalog ID", file=sys.stderr)
        return 2

    min_score = args.min_score
    if min_score is None:
        min_score = config.resolver_min_score

    try:
        resolver = TargetResolver.from_repo_data(min_score=min_score)
        matches = resolver.resolve(query, limit=args.limit)
    except AstrolabeError as e:
        return handle_error(args, "resolve", e)

    if not matches and not getattr(args, "json", False):
        print(f"Target not found: {query}", file=sys.stderr)
        return 2

    emit(
        args,
        "resolve",
        ok=bool(matches),
        data={
            "query": query,
            "min_score": min_score,
            "matches": [
                {
                    "name": match.record.name,
                    "id": match.record.id,
                    "ra_deg": match.record.ra_deg,
                    "dec_deg": match.record.dec_deg,
                    "score": match.match_score,
                    "reason": match.match_reason,
                }
                for match in matches
            ],
        },
        error=None
        if matches
        else error_object("not_found", f"Target not found: {query}"),
        human="\n".join(
            [f"Query: {query}", f"Min score: {min_score}"]
            + [
                f"- {match.record.name} ({match.record.id}) "
                f"RA {match.record.ra_deg:.5f} deg "
                f"Dec {match.record.dec_deg:.5f} deg "
                f"score={match.match_score:.2f} reason={match.match_reason}"
                for match in matches
            ]
        ),
    )
    return 0 if matches else 2


def _pointing_command_name(args) -> str:
    command = getattr(args, "command", "pointing")
    if command == "goto":
        return "goto"
    return f"{command}.{args.mode}"


def _resolve_pointing_target(args, config) -> tuple[float, float] | None:
    if args.target:
        from astrolabe.services.target.resolver import TargetResolver

        resolver = TargetResolver.from_repo_data(min_score=config.resolver_min_score)
        matches = resolver.resolve(args.target)
        if not matches:
            print(f"Target not found: {args.target}", file=sys.stderr)
            return None
        target = matches[0].record
        if getattr(args, "command", None) == "goto" and not getattr(
            args, "json", False
        ):
            print(
                f"Resolved '{args.target}' -> {target.name} ({target.id})",
                file=sys.stderr,
            )
        return target.ra_deg, target.dec_deg

    if args.ra_deg is None or args.dec_deg is None:
        prefix = "goto" if getattr(args, "command", None) == "goto" else "pointing goto"
        print(
            f"{prefix} requires --target or both --ra-deg and --dec-deg",
            file=sys.stderr,
        )
        return None
    return args.ra_deg, args.dec_deg


def run_align(args) -> int:
    config = prepare(args)
    mount, camera, solver = mount_camera_solver(config)
    note_dry_run(args, getattr(args, "command", "pointing"))

    model_path = default_model_path() if args.mode == "goto" else None
    model = (
        load_pointing_model(model_path) if model_path is not None else PointingModel()
    )
    service = PointingService(mount, camera, solver, model=model)
    command_name = _pointing_command_name(args)

    try:
        if args.mode == "solve":
            result = service.solve_current(exposure_s=args.exposure)
            is_align_alias = getattr(args, "command", None) == "align"
            return emit_result(
                args,
                command_name,
                result,
                failure_code="align_failed"
                if is_align_alias
                else "pointing_solve_failed",
                failure_message="align solve failed"
                if is_align_alias
                else "pointing solve failed",
                human=format_solve_summary(result),
            )

        if args.mode != "goto":
            print("Unknown pointing mode.", file=sys.stderr)
            return 2

        target = _resolve_pointing_target(args, config)
        if target is None:
            return 2
        target_ra_deg, target_dec_deg = target
        result = service.point_to(
            math.radians(target_ra_deg),
            math.radians(target_dec_deg),
            exposure_s=getattr(args, "exposure", None),
        )
        if result.model_updated and model_path is not None:
            save_pointing_model(model, model_path)

        failure_message = (
            result.message or result.solve.message or "pointing goto failed"
        )
        if result.success:
            human = (
                f"Final error: {result.final_error_arcsec:.1f} arcsec"
                if result.final_error_arcsec is not None
                else "Final error: unknown"
            )
        else:
            human = f"Pointing goto failed: {failure_message}"

        failure_code = (
            "goto_failed"
            if getattr(args, "command", None) == "goto"
            else "pointing_goto_failed"
        )
        return emit_result(
            args,
            command_name,
            result,
            ok=result.success,
            failure_code=failure_code,
            failure_message=failure_message,
            data={
                "target_ra_deg": target_ra_deg,
                "target_dec_deg": target_dec_deg,
                "command_ra_deg": math.degrees(result.command_ra_rad),
                "command_dec_deg": math.degrees(result.command_dec_rad),
                "solve": result.solve.__dict__,
                "final_error_arcsec": result.final_error_arcsec,
            },
            human=human,
        )
    except AstrolabeError as e:
        return handle_error(args, command_name, e)


def run_polar(args) -> int:
    config = prepare(args)
    mount, camera, solver = mount_camera_solver(config)
    note_dry_run(args, "polar")
    service = PolarAlignService(mount, camera, solver)

    try:
        result = service.run(
            ra_rotation_rad=math.radians(args.ra_rotation_deg),
            site_latitude_rad=math.radians(args.latitude_deg),
            exposure_s=args.exposure,
            settle_time_s=args.settle_time,
            num_poses=getattr(args, "num_poses", _POLAR_MIN_POSES),
        )
        success = (
            result.alt_correction_arcsec is not None
            and result.az_correction_arcsec is not None
        )
        human = (
            "\n".join(
                [
                    f"Altitude correction (arcsec): {result.alt_correction_arcsec}",
                    f"Azimuth correction (arcsec): {result.az_correction_arcsec}",
                    f"Residual (arcsec): {result.residual_arcsec}",
                    f"Confidence: {result.confidence}",
                ]
            )
            if success
            else f"Polar alignment failed: {result.message}"
        )
        return emit_result(
            args,
            "polar",
            result,
            ok=success,
            failure_code="polar_failed",
            failure_message="polar alignment failed",
            human=human,
            human_stream=None if success else sys.stderr,
        )
    except AstrolabeError as e:
        return handle_error(args, "polar", e)


def run_guide(args) -> int:
    config = prepare(args)
    service = GuidingService(get_mount_backend(config), get_camera_backend(config))
    note_dry_run(args, "guide")

    try:
        if args.action == "calibrate":
            result = service.calibrate(duration_s=args.duration)
            return emit_result(
                args,
                "guide",
                result,
                failure_code="guide_failed",
                failure_message="guide calibration failed",
                human=f"Success: {result.success}\nMessage: {result.message}",
            )

        if args.action == "start":
            service.start(
                aggression=args.aggression, min_move_arcsec=args.min_move_arcsec
            )
            emit(args, "guide.start", ok=True)
            return 0

        if args.action == "stop":
            service.stop()
            emit(args, "guide.stop", ok=True)
            return 0

        if args.action == "status":
            status = service.status()
            emit(
                args,
                "guide.status",
                ok=True,
                data=status.__dict__,
                human="\n".join(
                    [
                        f"Running: {status.running}",
                        f"RMS (arcsec): {status.rms_arcsec}",
                        f"Star lost: {status.star_lost}",
                        f"Last error (arcsec): {status.last_error_arcsec}",
                    ]
                ),
            )
            return 0

        print("Unknown guiding action.", file=sys.stderr)
        return 2
    except AstrolabeError as e:
        action = getattr(args, "action", None)
        return handle_error(args, f"guide.{action}" if action else "guide", e)


def run_plan(args) -> int:
    config = prepare(args)
    planner = Planner(config)
    note_dry_run(args, "plan")

    try:
        if args.window_start_utc and args.window_start_local:
            raise ValueError("Provide either --start-utc or --start-local, not both")
        if args.window_end_utc and args.window_end_local:
            raise ValueError("Provide either --end-utc or --end-local, not both")

        window_start = _parse_datetime_arg(args.window_start_utc)
        window_end = _parse_datetime_arg(args.window_end_utc)
        if window_start is None:
            window_start = _parse_datetime_local_arg(args.window_start_local)
        if window_end is None:
            window_end = _parse_datetime_local_arg(args.window_end_local)

        location = _parse_location_args(args)
        result = planner.plan(
            window_start_utc=window_start,
            window_end_utc=window_end,
            location=location,
            constraints=None,
            mode=getattr(args, "mode", None),
            limit=getattr(args, "limit", None),
        )
        emit(
            args,
            "plan",
            ok=True,
            data=asdict(result),
            human=format_plan_text(result, verbose=getattr(args, "verbose", False)),
            json_default=str,
        )
        return 0
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    except AstrolabeError as e:
        return handle_error(args, "plan", e)


def run_update(args) -> int:
    init_logging(getattr(args, "log_level", None))
    note_dry_run(args, "update")

    try:
        if args.dataset != "catalog":
            print("Unknown update dataset.", file=sys.stderr)
            return 2

        show_progress = not getattr(args, "json", False)
        catalog_dataset = getattr(args, "catalog_dataset", None)
        results = []

        if catalog_dataset in (None, "openngc"):
            openngc_result = update_catalog(
                source=getattr(args, "source", None),
                version=getattr(args, "version", None),
                output_path=getattr(args, "output", None),
                show_progress=show_progress,
            )
            results.append(
                (
                    "update.catalog.openngc",
                    openngc_result,
                    [
                        "OpenNGC update complete.",
                        f"Source: {openngc_result['source']}",
                        f"Cache: {openngc_result['cache_dir']}",
                        f"Output: {openngc_result['output_path']}",
                        f"Targets: {openngc_result['targets_written']}",
                    ],
                )
            )

        if catalog_dataset in (None, "hip"):
            max_mag = getattr(args, "max_mag", None)
            if max_mag is None:
                max_mag = load_config(config_path(args)).resolver_hip_max_mag
            hip_result = update_hipparcos(
                source=getattr(args, "source", None),
                output_path=getattr(args, "output", None),
                max_mag=max_mag,
                verify_ssl=not getattr(args, "insecure", False),
                show_progress=show_progress,
            )
            results.append(
                (
                    "update.catalog.hip",
                    hip_result,
                    [
                        "Hipparcos subset update complete.",
                        f"Source: {hip_result['source']}",
                        f"Cache: {hip_result['cache_dir']}",
                        f"Output: {hip_result['output_path']}",
                        f"Stars: {hip_result['stars_written']}",
                        f"Max mag: {hip_result['max_mag']}",
                    ],
                )
            )

        if catalog_dataset in (None, "bsc"):
            bsc_result = update_bsc_crosswalk(
                source=getattr(args, "source", None),
                output_path=getattr(args, "output", None),
                verify_ssl=not getattr(args, "insecure", False),
                show_progress=show_progress,
            )
            results.append(
                (
                    "update.catalog.bsc",
                    bsc_result,
                    [
                        "BSC crosswalk update complete.",
                        f"Source: {bsc_result['source']}",
                        f"HIP Source: {bsc_result['hip_source']}",
                        f"Cache: {bsc_result['cache_dir']}",
                        f"Output: {bsc_result['output_path']}",
                        f"Aliases: {bsc_result['aliases_written']}",
                    ],
                )
            )

        if not results:
            print("Unknown catalog dataset.", file=sys.stderr)
            return 2

        emit(
            args,
            "update.catalog",
            ok=True,
            data={name: data for name, data, _ in results},
            human="\n".join(line for _, _, summary in results for line in summary),
        )
        return 0
    except Exception as e:
        return emit_error(
            args,
            f"update.{args.dataset}",
            code="update_failed",
            message=str(e),
            human=f"Update failed: {e}",
        )
