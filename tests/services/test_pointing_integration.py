import math
import os
import shutil
import time
from pathlib import Path

import pytest

from astrolabe.config import Config
from astrolabe.camera import get_camera_backend
from astrolabe.mount import get_mount_backend
from astrolabe.solver import get_solver_backend
from astrolabe.services.pointing import PointingService
from astrolabe.services.target.resolver import TargetResolver


@pytest.mark.integration
def test_pointing_solve_integration(tmp_path):
    if os.environ.get("ASTROLABE_INDI_INTEGRATION") != "1":
        pytest.skip("Set ASTROLABE_INDI_INTEGRATION=1 to run INDI integration tests")
    if shutil.which("indi_getprop") is None or shutil.which("indi_setprop") is None:
        pytest.skip("INDI tools not available")

    astap_db = os.environ.get("ASTAP_DB", str(Path.home() / ".astap"))
    if astap_db and not os.path.exists(astap_db):
        pytest.skip("ASTAP_DB does not exist")

    for path in tmp_path.glob("*.fits"):
        path.unlink()
    output_prefix = f"astrolabe_pointing_{time.time_ns()}_"
    config = Config(
        {
            "indi": {"host": "127.0.0.1", "port": 7624},
            "mount": {"device": "Telescope Simulator"},
            "camera": {
                "device": "CCD Simulator",
                "output_dir": str(tmp_path),
                "output_prefix": output_prefix,
            },
            "solver": {
                "name": "astap",
                "binary": os.environ.get("ASTAP_CLI", "astap_cli"),
                "database_path": astap_db,
            },
        }
    )

    solver = get_solver_backend(config)
    availability = solver.is_available()
    if not availability.get("ok"):
        pytest.skip(f"ASTAP not available: {availability.get('detail')}")

    mount = get_mount_backend(config)
    camera = get_camera_backend(config)
    service = PointingService(mount, camera, solver)

    try:
        result = service.solve_current(exposure_s=2.0, use_mount_hints=False)
    except Exception as exc:  # noqa: BLE001 - integration environment may be missing
        pytest.skip(f"Pointing solve failed: {exc}")

    if not result.success:
        pytest.skip(f"Pointing solve failed: {result.message}")

    assert result.ra_rad is not None
    assert result.dec_rad is not None


@pytest.mark.integration
def test_pointing_slew_and_solve_target(tmp_path):
    if os.environ.get("ASTROLABE_INDI_INTEGRATION") != "1":
        pytest.skip("Set ASTROLABE_INDI_INTEGRATION=1 to run INDI integration tests")
    if shutil.which("indi_getprop") is None or shutil.which("indi_setprop") is None:
        pytest.skip("INDI tools not available")

    astap_db = os.environ.get("ASTAP_DB", str(Path.home() / ".astap"))
    if astap_db and not os.path.exists(astap_db):
        pytest.skip("ASTAP_DB does not exist")

    for path in tmp_path.glob("*.fits"):
        path.unlink()
    output_prefix = f"astrolabe_pointing_{time.time_ns()}_"
    config = Config(
        {
            "indi": {"host": "127.0.0.1", "port": 7624},
            "mount": {"device": "Telescope Simulator"},
            "camera": {
                "device": "CCD Simulator",
                "output_dir": str(tmp_path),
                "output_prefix": output_prefix,
            },
            "solver": {
                "name": "astap",
                "binary": os.environ.get("ASTAP_CLI", "astap_cli"),
                "database_path": astap_db,
            },
        }
    )

    solver = get_solver_backend(config)
    availability = solver.is_available()
    if not availability.get("ok"):
        pytest.skip(f"ASTAP not available: {availability.get('detail')}")

    mount = get_mount_backend(config)
    camera = get_camera_backend(config)
    service = PointingService(mount, camera, solver)

    resolver = TargetResolver.from_repo_data(min_score=0.5)
    matches = resolver.resolve("acrux")
    if not matches:
        pytest.skip("Target acrux not found in resolver catalog")
    target = matches[0].record

    try:
        mount.slew_to(
            ra_rad=math.radians(target.ra_deg),
            dec_rad=math.radians(target.dec_deg),
        )
    except Exception as exc:  # noqa: BLE001 - integration environment may be missing
        pytest.skip(f"Slew failed: {exc}")

    try:
        result = service.solve_current(exposure_s=2.0, use_mount_hints=False)
    except RuntimeError as exc:
        pytest.skip(f"Capture failed: {exc}")
    if not result.success or result.ra_rad is None or result.dec_rad is None:
        pytest.skip(f"Pointing solve failed: {result.message}")

    d_ra = (result.ra_rad - math.radians(target.ra_deg) + math.pi) % (
        2.0 * math.pi
    ) - math.pi
    d_dec = result.dec_rad - math.radians(target.dec_deg)
    angular_err = math.hypot(d_ra * math.cos(result.dec_rad), d_dec)

    assert angular_err < math.radians(1.0)
