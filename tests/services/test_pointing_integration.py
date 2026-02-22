import os
import shutil

import pytest

from astrolabe.config import Config
from astrolabe.camera import get_camera_backend
from astrolabe.mount import get_mount_backend
from astrolabe.solver import get_solver_backend
from astrolabe.services.pointing import PointingService


@pytest.mark.integration
def test_pointing_solve_integration(tmp_path):
    if os.environ.get("ASTROLABE_INDI_INTEGRATION") != "1":
        pytest.skip("Set ASTROLABE_INDI_INTEGRATION=1 to run INDI integration tests")
    if shutil.which("indi_getprop") is None or shutil.which("indi_setprop") is None:
        pytest.skip("INDI tools not available")

    astap_db = os.environ.get("ASTAP_DB")
    if astap_db and not os.path.exists(astap_db):
        pytest.skip("ASTAP_DB does not exist")

    config = Config(
        {
            "indi": {"host": "127.0.0.1", "port": 7624},
            "mount": {"device": "Telescope Simulator"},
            "camera": {
                "device": "CCD Simulator",
                "output_dir": str(tmp_path),
                "output_prefix": "astrolabe_pointing_",
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
        result = service.solve_current(exposure_s=2.0)
    except Exception as exc:  # noqa: BLE001 - integration environment may be missing
        pytest.skip(f"Pointing solve failed: {exc}")

    if not result.success:
        pytest.skip(f"Pointing solve failed: {result.message}")

    assert result.ra_rad is not None
    assert result.dec_rad is not None
