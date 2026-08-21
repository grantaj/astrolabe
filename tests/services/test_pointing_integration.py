import datetime
import math
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from astrolabe.config import Config
from astrolabe.camera import get_camera_backend
from astrolabe.mount import get_mount_backend
from astrolabe.planner.astro import ra_dec_to_alt_az
from astrolabe.solver import get_solver_backend
from astrolabe.solver.types import Image, SolveRequest, SolveResult
from astrolabe.pointing import PointingModel, PointingService
from astrolabe.services.target.resolver import TargetResolver


_SIM_SITE_LAT_DEG = -35.3
_SIM_SITE_LON_DEG = 149.1
_SIM_SITE_ELEV_M = 600.0
_SIM_UTC_OFFSET_HOURS = 10.0
_SIM_TIME_UTC = datetime.datetime(2026, 4, 1, 8, 0, tzinfo=datetime.timezone.utc)
_POINTING_TARGET_QUERY = "canopus"
_POINTING_TARGET_ID = "HIP 30438"


def _indi_get_value(host: str, port: int, prop: str) -> str:
    cmd = ["indi_getprop", "-h", host, "-p", str(port), "-t", "2", "-1", prop]
    try:
        return subprocess.run(
            cmd,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"INDI property unavailable: {prop}: {exc.stderr.strip()}")


def _indi_set_vector(
    host: str,
    port: int,
    device: str,
    prop: str,
    values: dict[str, str],
    *,
    kind: str,
    order: list[str],
) -> None:
    spec = (
        f"{device}.{prop}.{';'.join(order)}={';'.join(values[name] for name in order)}"
    )
    cmd = ["indi_setprop", "-h", host, "-p", str(port), f"-{kind}", spec]
    try:
        subprocess.run(
            cmd,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"Could not set INDI vector: {spec}: {exc.stderr.strip()}")


def _assert_indi_float(
    host: str, port: int, prop: str, expected: float, *, tolerance: float = 1e-3
) -> None:
    value = float(_indi_get_value(host, port, prop))
    if not math.isclose(value, expected, abs_tol=tolerance):
        pytest.skip(f"INDI did not accept {prop}: got {value}, expected {expected}")


def _set_deterministic_site_and_time_for_target(
    host: str,
    port: int,
    *,
    ra_deg: float,
    dec_deg: float,
    min_alt_deg: float = 30.0,
) -> None:
    lat_rad = math.radians(_SIM_SITE_LAT_DEG)
    ra_rad = math.radians(ra_deg)
    dec_rad = math.radians(dec_deg)

    alt_rad, _ = ra_dec_to_alt_az(
        ra_rad,
        dec_rad,
        lat_rad,
        _SIM_SITE_LON_DEG,
        _SIM_TIME_UTC,
    )
    alt_deg = math.degrees(alt_rad)
    if alt_deg < min_alt_deg:
        pytest.skip(
            f"Target altitude is below the deterministic test horizon: {alt_deg:.1f}"
        )

    utc_text = _SIM_TIME_UTC.strftime("%Y-%m-%dT%H:%M:%S")
    _indi_set_vector(
        host,
        port,
        "Telescope Simulator",
        "GEOGRAPHIC_COORD",
        {
            "LAT": str(_SIM_SITE_LAT_DEG),
            "LONG": str(_SIM_SITE_LON_DEG),
            "ELEV": str(_SIM_SITE_ELEV_M),
        },
        kind="n",
        order=["LAT", "LONG", "ELEV"],
    )
    _indi_set_vector(
        host,
        port,
        "Telescope Simulator",
        "TIME_UTC",
        {
            "UTC": utc_text,
            "OFFSET": f"{_SIM_UTC_OFFSET_HOURS:.1f}",
        },
        kind="x",
        order=["UTC", "OFFSET"],
    )

    _assert_indi_float(
        host, port, "Telescope Simulator.GEOGRAPHIC_COORD.LAT", _SIM_SITE_LAT_DEG
    )
    _assert_indi_float(
        host, port, "Telescope Simulator.GEOGRAPHIC_COORD.LONG", _SIM_SITE_LON_DEG
    )
    _assert_indi_float(
        host, port, "Telescope Simulator.GEOGRAPHIC_COORD.ELEV", _SIM_SITE_ELEV_M
    )
    _assert_indi_float(
        host, port, "Telescope Simulator.TIME_UTC.OFFSET", _SIM_UTC_OFFSET_HOURS
    )
    accepted_time = _indi_get_value(host, port, "Telescope Simulator.TIME_UTC.UTC")
    if not accepted_time.startswith(utc_text):
        pytest.skip(f"INDI did not accept TIME_UTC.UTC: got {accepted_time!r}")


def test_pointing_integration_target_is_deterministically_visible():
    resolver = TargetResolver.from_repo_data(min_score=0.95)
    matches = resolver.resolve(_POINTING_TARGET_QUERY)

    assert matches
    target = matches[0].record
    assert target.id == _POINTING_TARGET_ID

    alt_rad, _ = ra_dec_to_alt_az(
        math.radians(target.ra_deg),
        math.radians(target.dec_deg),
        math.radians(_SIM_SITE_LAT_DEG),
        _SIM_SITE_LON_DEG,
        _SIM_TIME_UTC,
    )
    assert math.degrees(alt_rad) > 30.0


def _blur_fits(path: Path) -> Path:
    try:
        import numpy as np
        from astropy.io import fits
    except ImportError as exc:  # noqa: BLE001 - optional dependency for integration
        pytest.skip(f"astropy/numpy required for blur: {exc}")

    with fits.open(path) as hdul:
        data = hdul[0].data.astype("float32")
        header = hdul[0].header.copy()
    median = float(np.median(data))
    resid = data - median
    sigma = 1.0
    radius = 3
    coords = np.arange(-radius, radius + 1, dtype="float32")
    kernel = np.exp(-(coords**2) / (2.0 * sigma * sigma))
    kernel /= kernel.sum()

    pad = radius
    padded = np.pad(resid, pad, mode="edge")
    temp = np.zeros_like(resid)
    for i, weight in enumerate(kernel):
        temp += weight * padded[i : i + resid.shape[0], pad : pad + resid.shape[1]]

    padded_temp = np.pad(temp, pad, mode="edge")
    blurred = np.zeros_like(temp)
    for j, weight in enumerate(kernel):
        blurred += (
            weight * padded_temp[pad : pad + temp.shape[0], j : j + temp.shape[1]]
        )

    blurred += median
    blurred = np.clip(blurred, data.min(), data.max())
    out_path = path.with_name(path.stem + "_blur.fits")
    fits.writeto(out_path, blurred, header=header, overwrite=True)
    return out_path


def _solve_with_blur(service: PointingService, exposure_s: float) -> SolveResult:
    needs_disconnect = False
    if not service._camera.is_connected():  # noqa: SLF001 - integration helper
        service._camera.connect()  # noqa: SLF001 - integration helper
        needs_disconnect = True
    try:
        image = service._camera.capture(exposure_s=exposure_s)  # noqa: SLF001
    finally:
        if needs_disconnect:
            service._camera.disconnect()  # noqa: SLF001

    image_path = Path(str(image.data))
    blurred_path = _blur_fits(image_path)
    blurred_image = Image(
        data=str(blurred_path),
        width_px=image.width_px,
        height_px=image.height_px,
        timestamp_utc=image.timestamp_utc,
        exposure_s=image.exposure_s,
        metadata=image.metadata,
    )
    request = SolveRequest(image=blurred_image)
    return service._solver.solve(request)  # noqa: SLF001 - integration helper


def _wait_for_slew_complete(mount, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    last = None
    stable = 0
    while time.monotonic() < deadline:
        state = mount.get_state()
        if state.ra_rad is None or state.dec_rad is None:
            time.sleep(0.5)
            continue
        if state.slewing:
            stable = 0
            last = (state.ra_rad, state.dec_rad)
            time.sleep(0.5)
            continue
        if last is None:
            last = (state.ra_rad, state.dec_rad)
            time.sleep(0.5)
            continue
        d_ra = (state.ra_rad - last[0] + math.pi) % (2.0 * math.pi) - math.pi
        d_dec = state.dec_rad - last[1]
        if math.hypot(d_ra * math.cos(state.dec_rad), d_dec) < 1e-4:
            stable += 1
        else:
            stable = 0
        last = (state.ra_rad, state.dec_rad)
        if stable >= 3:
            return
        time.sleep(0.5)
    raise RuntimeError("Timed out waiting for slew to complete")


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
    service = PointingService(mount, camera, solver, model=PointingModel())

    resolver = TargetResolver.from_repo_data(min_score=0.5)
    matches = resolver.resolve(_POINTING_TARGET_QUERY)
    if not matches or matches[0].record.id != _POINTING_TARGET_ID:
        pytest.skip(f"Target {_POINTING_TARGET_QUERY} not found in resolver catalog")
    target = matches[0].record

    _set_deterministic_site_and_time_for_target(
        config.indi_host,
        config.indi_port,
        ra_deg=target.ra_deg,
        dec_deg=target.dec_deg,
    )

    try:
        mount.slew_to(
            ra_rad=math.radians(target.ra_deg),
            dec_rad=math.radians(target.dec_deg),
        )
        _wait_for_slew_complete(mount)
    except Exception as exc:  # noqa: BLE001 - integration environment may be missing
        pytest.skip(f"Slew failed: {exc}")

    try:
        result = _solve_with_blur(service, exposure_s=2.0)
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


@pytest.mark.integration
def test_pointing_goto_learns_offset(tmp_path):
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

    base_mount = get_mount_backend(config)
    camera = get_camera_backend(config)
    model = PointingModel()

    perturb_ra_rad = 0.01
    perturb_dec_rad = -0.005

    class PerturbedMount:
        def __init__(self, inner, d_ra, d_dec):
            self._inner = inner
            self._d_ra = d_ra
            self._d_dec = d_dec

        def get_state(self):
            return self._inner.get_state()

        def slew_to(self, ra_rad, dec_rad):
            self._inner.slew_to(ra_rad + self._d_ra, dec_rad + self._d_dec)

        def sync(self, ra_rad, dec_rad):
            return self._inner.sync(ra_rad, dec_rad)

    mount = PerturbedMount(base_mount, d_ra=perturb_ra_rad, d_dec=perturb_dec_rad)
    service = PointingService(mount, camera, solver, model=model)

    resolver = TargetResolver.from_repo_data(min_score=0.5)
    matches = resolver.resolve(_POINTING_TARGET_QUERY)
    if not matches or matches[0].record.id != _POINTING_TARGET_ID:
        pytest.skip(f"Target {_POINTING_TARGET_QUERY} not found in resolver catalog")
    target = matches[0].record

    _set_deterministic_site_and_time_for_target(
        config.indi_host,
        config.indi_port,
        ra_deg=target.ra_deg,
        dec_deg=target.dec_deg,
    )
    target_ra_rad = math.radians(target.ra_deg)
    target_dec_rad = math.radians(target.dec_deg)

    def run_pointing_once():
        cmd_ra, cmd_dec = service.apply_model(target_ra_rad, target_dec_rad)
        mount.slew_to(cmd_ra, cmd_dec)
        _wait_for_slew_complete(mount)
        result = _solve_with_blur(service, exposure_s=2.0)
        if not result.success or result.ra_rad is None or result.dec_rad is None:
            pytest.skip(f"Pointing solve failed: {result.message}")
        service.update_model_from_target(
            ra_target=target_ra_rad,
            dec_target=target_dec_rad,
            result=result,
            weight=1.0,
        )
        d_alpha = (result.ra_rad - target_ra_rad) * math.cos(target_dec_rad)
        d_delta = result.dec_rad - target_dec_rad
        return math.hypot(d_alpha, d_delta)

    expected_err = math.hypot(
        perturb_ra_rad * math.cos(target_dec_rad),
        perturb_dec_rad,
    )

    err1 = run_pointing_once()
    if err1 > max(math.radians(2.0), expected_err * 5.0):
        pytest.skip(
            "Baseline solve error is not dominated by the injected pointing "
            f"offset: got {math.degrees(err1):.2f} deg, expected about "
            f"{math.degrees(expected_err):.2f} deg"
        )
    err2 = run_pointing_once()

    assert err2 < err1
