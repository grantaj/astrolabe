import datetime
import json
import math
import subprocess
import sys
import types

import numpy as np
import pytest

from astrolabe.camera.pixels import write_fits_image
from astrolabe.solver import get_solver_backend
from astrolabe.solver.astap import AstapSolverBackend
from astrolabe.solver.tetra3 import (
    Tetra3SolverBackend,
    fov_estimate_deg,
    pixel_scale_arcsec_from_fov,
    rotation_rad_from_roll_deg,
)
from astrolabe.solver.types import Image, SolveRequest

DEFAULT_DB_PROPS = {"min_fov": 10.0, "max_fov": 30.0}
SOLVED = {
    "RA": 83.0,
    "Dec": -5.0,
    "Roll": 160.0,
    "FOV": 19.8,
    "RMSE": 6.5,
    "Matches": 30,
    "Prob": 1e-40,
}


def assert_failure(result, fragment):
    assert result.success is False
    assert result.message is not None and fragment in result.message


def make_image(data, width_px=1024, height_px=768):
    return Image(
        data=data,
        width_px=width_px,
        height_px=height_px,
        timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
        exposure_s=2.0,
        metadata={},
    )


def fake_tetra3(
    solution=None,
    db_props=None,
    has_database=True,
    load_error=None,
    solve_error=None,
    calls=None,
):
    module = types.ModuleType("tetra3")

    class FakeTetra3:
        """Binds the real tetra3 parameter names so a wrong call raises TypeError."""

        def __init__(self, load_database="default_database", debug_folder=None):
            if load_error is not None:
                raise load_error
            self.has_database = has_database
            self.database_properties = (
                DEFAULT_DB_PROPS if db_props is None else db_props
            )
            module.instances += 1

        def solve_from_centroids(
            self,
            star_centroids,
            size,
            fov_estimate=None,
            fov_max_error=None,
            pattern_checking_stars=8,
            match_radius=0.01,
            match_threshold=0.001,
            solve_timeout=None,
            target_pixel=None,
            distortion=0,
            return_matches=False,
            return_visual=False,
        ):
            if solve_error is not None:
                raise solve_error
            assert len(size) == 2 and size[0] < size[1], "size is (height, width)"
            if calls is not None:
                calls.append(
                    {
                        "size": size,
                        "fov_estimate": fov_estimate,
                        "fov_max_error": fov_max_error,
                        "solve_timeout": solve_timeout,
                    }
                )
            return dict(SOLVED if solution is None else solution)

    def get_centroids_from_image(
        image,
        sigma=2,
        image_th=None,
        crop=None,
        downsample=None,
        filtsize=25,
        bg_sub_mode="local_mean",
        sigma_mode="global_root_square",
        binary_open=True,
        centroid_window=None,
        max_area=100,
        min_area=5,
        max_sum=None,
        min_sum=None,
        max_axis_ratio=None,
        max_returned=None,
        return_moments=False,
        return_images=False,
    ):
        return np.zeros((10, 2))

    module.instances = 0  # ty: ignore[unresolved-attribute]
    module.Tetra3 = FakeTetra3  # ty: ignore[unresolved-attribute]
    module.get_centroids_from_image = (  # ty: ignore[unresolved-attribute]
        get_centroids_from_image
    )
    return module


@pytest.fixture
def install_fake_tetra3(monkeypatch):
    def install(**kwargs):
        module = fake_tetra3(**kwargs)
        monkeypatch.setitem(sys.modules, "tetra3", module)
        return module

    return install


@pytest.fixture
def fits_image(tmp_path):
    path = tmp_path / "frame.fits"
    write_fits_image(path, np.zeros((768, 1024), dtype=np.uint16))
    return make_image(str(path))


# --- pure conversions ------------------------------------------------------


@pytest.mark.parametrize(
    "roll_deg,expected_crota_deg",
    [(180.0, 0.0), (160.0, 20.0), (215.0, -35.0), (0.0, 180.0), (270.0, -90.0)],
)
def test_roll_maps_to_fits_crota_rotation(roll_deg, expected_crota_deg):
    assert rotation_rad_from_roll_deg(roll_deg) == pytest.approx(
        math.radians(expected_crota_deg)
    )


def test_fov_maps_to_tangent_plane_pixel_scale():
    # 20 deg across 1024 pixels in the tangent plane solves to a 19.8005 deg FOV.
    assert pixel_scale_arcsec_from_fov(19.800503, 1024) == pytest.approx(
        20.0 * 3600 / 1024, rel=1e-5
    )


@pytest.mark.parametrize("fov_deg", [0.5, 2.66, 20.0, 60.0])
@pytest.mark.parametrize("width_px", [640, 1024, 4096])
def test_fov_and_pixel_scale_round_trip(fov_deg, width_px):
    scale = pixel_scale_arcsec_from_fov(fov_deg, width_px)
    assert fov_estimate_deg(scale, width_px) == pytest.approx(fov_deg)


# --- result mapping --------------------------------------------------------


def test_solve_maps_full_result(install_fake_tetra3, fits_image):
    install_fake_tetra3()
    backend = Tetra3SolverBackend("default_database", fallback_fov_deg=20.0)
    result = backend.solve(SolveRequest(image=fits_image))

    assert result.success is True
    assert result.ra_rad == pytest.approx(math.radians(83.0))
    assert result.dec_rad == pytest.approx(math.radians(-5.0))
    assert result.rotation_rad == pytest.approx(math.radians(20.0))
    assert result.pixel_scale_arcsec == pytest.approx(
        pixel_scale_arcsec_from_fov(19.8, 1024)
    )
    assert result.rms_arcsec == pytest.approx(6.5)
    assert result.num_stars == 30
    assert result.message is not None and result.message.startswith("tetra3 solve")
    assert result.raw_output is not None
    assert json.loads(result.raw_output)["Prob"] == pytest.approx(1e-40)


def test_unsolved_reports_structured_failure(install_fake_tetra3, fits_image):
    install_fake_tetra3(solution={"RA": None, "Dec": None, "Roll": None, "FOV": None})
    backend = Tetra3SolverBackend("default_database", fallback_fov_deg=20.0)
    result = backend.solve(SolveRequest(image=fits_image))

    assert_failure(result, "no match")


def test_tetra3_exception_becomes_structured_failure(install_fake_tetra3, fits_image):
    install_fake_tetra3(solve_error=RuntimeError("pattern table corrupt"))
    backend = Tetra3SolverBackend("default_database", fallback_fov_deg=20.0)
    result = backend.solve(SolveRequest(image=fits_image))

    assert_failure(result, "RuntimeError")
    assert_failure(result, "pattern table corrupt")


def test_missing_tetra3_becomes_structured_failure(monkeypatch, fits_image):
    monkeypatch.setitem(sys.modules, "tetra3", None)
    backend = Tetra3SolverBackend("default_database", fallback_fov_deg=20.0)
    result = backend.solve(SolveRequest(image=fits_image))

    assert_failure(result, "--extra tetra3")


def test_database_load_failure_becomes_structured_failure(
    install_fake_tetra3, fits_image
):
    install_fake_tetra3(load_error=OSError("no such file"))
    backend = Tetra3SolverBackend("/nope.npz", fallback_fov_deg=20.0)
    result = backend.solve(SolveRequest(image=fits_image))

    assert_failure(result, "/nope.npz")
    assert_failure(result, "no such file")


def test_empty_database_becomes_structured_failure(install_fake_tetra3, fits_image):
    install_fake_tetra3(has_database=False)
    backend = Tetra3SolverBackend("default_database", fallback_fov_deg=20.0)
    result = backend.solve(SolveRequest(image=fits_image))

    assert_failure(result, "generate_database")


def test_database_is_loaded_once_per_instance(install_fake_tetra3, fits_image):
    module = install_fake_tetra3()
    backend = Tetra3SolverBackend("default_database", fallback_fov_deg=20.0)
    backend.solve(SolveRequest(image=fits_image))
    backend.solve(SolveRequest(image=fits_image))

    assert module.instances == 1


# --- FOV and hints ---------------------------------------------------------


def test_scale_hint_and_width_derive_fov(install_fake_tetra3, fits_image):
    calls = []
    install_fake_tetra3(db_props={"min_fov": 1.0, "max_fov": 30.0}, calls=calls)
    config = StubConfig("tetra3")
    config.solver_fov_deg = None
    config.solver_fov_tolerance_deg = 0.25
    backend = get_solver_backend(config)
    result = backend.solve(SolveRequest(image=fits_image, scale_hint_arcsec=5.0))

    assert result.success is True
    assert calls[0]["fov_estimate"] == pytest.approx(fov_estimate_deg(5.0, 1024))
    assert calls[0]["fov_max_error"] == pytest.approx(0.25)


def test_configured_fallback_fov_used_without_scale_hint(
    install_fake_tetra3, fits_image
):
    calls = []
    install_fake_tetra3(calls=calls)
    backend = Tetra3SolverBackend("default_database", fallback_fov_deg=20.0)
    backend.solve(SolveRequest(image=fits_image))

    assert calls[0]["fov_estimate"] == pytest.approx(20.0)


def test_decoded_width_is_used_when_metadata_width_is_unset(
    install_fake_tetra3, tmp_path
):
    calls = []
    install_fake_tetra3(db_props={"min_fov": 1.0, "max_fov": 30.0}, calls=calls)
    path = tmp_path / "frame.fits"
    write_fits_image(path, np.zeros((768, 1024), dtype=np.uint16))
    # `astrolabe solve` always sets width_px=0, so only the decoded frame counts.
    image = make_image(str(path), width_px=0, height_px=0)
    backend = Tetra3SolverBackend("default_database", fallback_fov_deg=20.0)
    result = backend.solve(SolveRequest(image=image, scale_hint_arcsec=5.0))

    assert calls[0]["fov_estimate"] == pytest.approx(fov_estimate_deg(5.0, 1024))
    assert result.pixel_scale_arcsec == pytest.approx(
        pixel_scale_arcsec_from_fov(19.8, 1024)
    )


def test_no_fov_information_fails_clearly(install_fake_tetra3, fits_image):
    install_fake_tetra3()
    backend = Tetra3SolverBackend("default_database")
    result = backend.solve(SolveRequest(image=fits_image))

    assert_failure(result, "fov_deg")


def test_database_fov_incompatibility_fails_clearly(install_fake_tetra3, fits_image):
    install_fake_tetra3()
    backend = Tetra3SolverBackend("default_database", fallback_fov_deg=2.66)
    result = backend.solve(SolveRequest(image=fits_image))

    assert_failure(result, "outside the tetra3 database range")
    assert_failure(result, "10.000-30.000")


def test_positional_hints_are_ignored(install_fake_tetra3, fits_image):
    calls = []
    install_fake_tetra3(calls=calls)
    backend = Tetra3SolverBackend("default_database", fallback_fov_deg=20.0)
    backend.solve(
        SolveRequest(
            image=fits_image,
            ra_hint_rad=1.0,
            dec_hint_rad=-0.1,
            search_radius_rad=0.05,
            parity_hint=1,
            timeout_s=4.0,
        )
    )

    assert calls[0]["solve_timeout"] == pytest.approx(4000.0)


def test_extra_options_are_ignored(install_fake_tetra3, fits_image):
    # `astrolabe solve --verbose` sets ASTAP CLI flags here; tetra3 takes none.
    install_fake_tetra3()
    backend = Tetra3SolverBackend("default_database", fallback_fov_deg=20.0)
    result = backend.solve(
        SolveRequest(image=fits_image, extra_options={"verbose": True})
    )

    assert result.success is True


# --- image payloads --------------------------------------------------------


def test_fits_path_payload_is_decoded(install_fake_tetra3, fits_image):
    calls = []
    install_fake_tetra3(calls=calls)
    backend = Tetra3SolverBackend("default_database", fallback_fov_deg=20.0)
    result = backend.solve(SolveRequest(image=fits_image))

    assert result.success is True
    assert calls[0]["size"] == (768, 1024)


def test_invalid_payload_fails_clearly(install_fake_tetra3):
    install_fake_tetra3()
    backend = Tetra3SolverBackend("default_database", fallback_fov_deg=20.0)
    result = backend.solve(SolveRequest(image=make_image(object())))

    assert_failure(result, "could not decode")


def test_non_2d_payload_fails_clearly(install_fake_tetra3):
    install_fake_tetra3()
    backend = Tetra3SolverBackend("default_database", fallback_fov_deg=20.0)
    image = make_image(np.zeros((4, 4, 3), dtype=np.uint16))
    result = backend.solve(SolveRequest(image=image))

    assert_failure(result, "2D monochrome")


# --- availability ----------------------------------------------------------


def test_is_available_reports_database(install_fake_tetra3):
    install_fake_tetra3()
    assert Tetra3SolverBackend("default_database").is_available() == {
        "ok": True,
        "detail": "database default_database loaded (FOV 10.00-30.00 deg)",
    }


def test_is_available_reports_missing_tetra3(monkeypatch):
    monkeypatch.setitem(sys.modules, "tetra3", None)
    available = Tetra3SolverBackend("default_database").is_available()

    assert available["ok"] is False
    assert "--extra tetra3" in available["detail"]


# --- backend selection -----------------------------------------------------


class StubConfig:
    solver_binary = "astap_cli"
    solver_database_path = "/db"
    solver_fov_deg = 2.66
    solver_fov_tolerance_deg = 0.5

    def __init__(self, solver_name):
        self.solver_name = solver_name


def test_selection_defaults_to_astap():
    backend = get_solver_backend(StubConfig(None))
    assert isinstance(backend, AstapSolverBackend)
    assert backend.binary == "astap_cli"
    assert backend.database_path == "/db"


def test_selection_astap_unchanged():
    assert isinstance(get_solver_backend(StubConfig("astap")), AstapSolverBackend)


def test_selection_tetra3():
    backend = get_solver_backend(StubConfig("tetra3"))
    assert isinstance(backend, Tetra3SolverBackend)
    assert backend.database_path == "/db"
    assert backend.fallback_fov_deg == 2.66
    assert backend.fov_tolerance_deg == 0.5


def test_selection_tetra3_without_fallback_fov():
    config = StubConfig("tetra3")
    config.solver_fov_deg = None
    backend = get_solver_backend(config)

    assert isinstance(backend, Tetra3SolverBackend)
    assert backend.database_path == "/db"
    assert backend.fallback_fov_deg is None


def test_selection_tetra3_without_database_raises():
    config = StubConfig("tetra3")
    config.solver_database_path = None
    with pytest.raises(ValueError, match="database_path"):
        get_solver_backend(config)


def test_selection_unknown_raises():
    with pytest.raises(ValueError, match="Unknown solver backend: sextractor"):
        get_solver_backend(StubConfig("sextractor"))


def test_importing_solver_package_does_not_import_tetra3():
    code = "import astrolabe.solver, sys; assert 'tetra3' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)


# --- integration -----------------------------------------------------------


@pytest.fixture(scope="session")
def tetra3_database():
    tetra3 = pytest.importorskip("tetra3")
    solver = tetra3.Tetra3(load_database="default_database")
    if not solver.has_database:
        pytest.skip("tetra3 default database unavailable")
    return solver


@pytest.fixture(scope="session")
def star_catalog(tetra3_database):
    from support.starfield import catalog_from_tetra3

    return catalog_from_tetra3(tetra3_database)


SYNTHETIC_RA_DEG = 83.0
SYNTHETIC_DEC_DEG = -5.0
SYNTHETIC_FOV_DEG = 20.0
SYNTHETIC_WIDTH = 1024
SYNTHETIC_HEIGHT = 768


def synthetic_field(tmp_path, catalog, rotation_deg=0.0, noise_sigma=0.0):
    from support.starfield import render_field

    pixels, header = render_field(
        catalog,
        ra_deg=SYNTHETIC_RA_DEG,
        dec_deg=SYNTHETIC_DEC_DEG,
        fov_deg=SYNTHETIC_FOV_DEG,
        width=SYNTHETIC_WIDTH,
        height=SYNTHETIC_HEIGHT,
        rotation_deg=rotation_deg,
        noise_sigma=noise_sigma,
    )
    path = tmp_path / "synthetic.fits"
    write_fits_image(path, pixels, extra_header=header)
    return make_image(str(path), SYNTHETIC_WIDTH, SYNTHETIC_HEIGHT)


@pytest.mark.integration
@pytest.mark.parametrize(
    "rotation_deg,noise_sigma,use_scale_hint",
    [
        (0.0, 0.0, False),
        (0.0, 0.0, True),
        (37.5, 0.0, False),
        (-37.5, 0.0, False),
        (179.0, 0.0, False),
        (-179.0, 0.0, False),
        (0.0, 40.0, False),
    ],
    ids=[
        "blind",
        "scale-hinted",
        "rotated",
        "counter-rotated",
        "near-half-turn",
        "near-negative-half-turn",
        "noisy",
    ],
)
def test_tetra3_solves_synthetic_field(
    tmp_path, star_catalog, rotation_deg, noise_sigma, use_scale_hint
):
    # The field is rendered from the database's own star table, so this
    # validates the RA/Dec, rotation and scale mapping conventions end to end,
    # not tetra3's robustness on real sky data.
    image = synthetic_field(tmp_path, star_catalog, rotation_deg, noise_sigma)
    true_scale_arcsec = SYNTHETIC_FOV_DEG * 3600 / SYNTHETIC_WIDTH
    backend = Tetra3SolverBackend(
        "default_database", fallback_fov_deg=SYNTHETIC_FOV_DEG
    )
    request = SolveRequest(
        image=image,
        scale_hint_arcsec=true_scale_arcsec if use_scale_hint else None,
    )

    result = backend.solve(request)

    assert result.success is True, result.message
    assert result.ra_rad is not None
    assert result.dec_rad is not None
    assert result.rotation_rad is not None
    assert result.num_stars is not None
    assert result.rms_arcsec is not None
    assert math.degrees(result.ra_rad) == pytest.approx(SYNTHETIC_RA_DEG, abs=0.02)
    assert math.degrees(result.dec_rad) == pytest.approx(SYNTHETIC_DEC_DEG, abs=0.02)
    assert math.degrees(result.rotation_rad) == pytest.approx(rotation_deg, abs=0.1)
    assert result.pixel_scale_arcsec == pytest.approx(true_scale_arcsec, rel=1e-3)
    assert result.num_stars >= 10
    assert result.rms_arcsec < 60.0


@pytest.mark.integration
def test_tetra3_is_available_integration(tetra3_database):
    available = Tetra3SolverBackend("default_database").is_available()
    assert available["ok"] is True
    assert "10.00-30.00" in available["detail"]
