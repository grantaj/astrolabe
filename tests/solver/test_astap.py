import pytest
from astrolabe.solver.astap import AstapSolverBackend
from astrolabe.solver.types import Image, SolveRequest
import datetime
from unittest.mock import patch
import os
from pathlib import Path
import subprocess
import sys
import shutil
import io
import math

TEST_TIMEOUT_S = 1.0


@pytest.fixture
def sample_fits_path():
    # Path to a sample FITS file in testdata/raw/
    return "testdata/raw/sample1.fits"


@pytest.fixture
def sample_image(sample_fits_path):
    return Image(
        data=sample_fits_path,
        width_px=1024,
        height_px=1024,
        timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
        exposure_s=2.0,
        metadata={},
    )


def test_astap_is_available_success():
    backend = AstapSolverBackend(binary="astap_cli")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        result = backend.is_available()
        assert result["ok"] is True
        assert "responds" in result["detail"]


def test_astap_is_available_not_found():
    backend = AstapSolverBackend(binary="not_a_real_binary")
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = backend.is_available()
        assert result["ok"] is False
        assert "not found" in result["detail"]


def test_astap_solve_placeholder(sample_image):
    backend = AstapSolverBackend(binary="astap_cli")

    def fake_exists(path):
        path_str = str(path)
        return path_str.endswith(".ini") or path_str.endswith(".wcs")

    def fake_open(path, *args, **kwargs):
        path_str = str(path)
        if path_str.endswith(".ini"):
            return io.StringIO(
                "CRVAL1=10\n"
                "CRVAL2=20\n"
                "CDELT1=0.0002777778\n"
                "CDELT2=0.0002777778\n"
                "CROTA1=0\n"
            )
        if path_str.endswith(".wcs"):
            return io.StringIO('Offset was 1.2"\n123 stars\n')
        raise FileNotFoundError(path)

    with (
        patch("subprocess.run") as mock_run,
        patch("os.path.exists", side_effect=fake_exists),
        patch("builtins.open", new=fake_open),
    ):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        request = SolveRequest(image=sample_image)
        result = backend.solve(request)
        assert result.success is True
        assert result.message is not None
        assert result.message.startswith("ASTAP solve succeeded")


def test_astap_hint_units():
    image = Image(
        data="testdata/raw/sample1.fits",
        width_px=1024,
        height_px=1024,
        timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
        exposure_s=2.0,
        metadata={},
    )
    request = SolveRequest(
        image=image,
        ra_hint_rad=math.radians(15.0),
        dec_hint_rad=math.radians(0.0),
        search_radius_rad=math.radians(5.0),
        timeout_s=TEST_TIMEOUT_S,
    )
    backend = AstapSolverBackend(binary="astap_cli")

    def fake_exists(path):
        return str(path).endswith(".ini")

    def fake_open(path, *args, **kwargs):
        return io.StringIO(
            "CRVAL1=10\nCRVAL2=20\nCDELT1=0.0002777778\nCDELT2=0.0002777778\nCROTA1=0\n"
        )

    with (
        patch("subprocess.run") as mock_run,
        patch("os.path.exists", side_effect=fake_exists),
        patch("builtins.open", new=fake_open),
    ):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        backend.solve(request)
        cmd = mock_run.call_args[0][0]
        assert "-ra" in cmd and "-spd" in cmd
        ra_value = float(cmd[cmd.index("-ra") + 1])
        spd_value = float(cmd[cmd.index("-spd") + 1])
        assert ra_value == pytest.approx(1.0, rel=0, abs=1e-9)
        assert spd_value == pytest.approx(90.0, rel=0, abs=1e-9)
        assert "-radius" in cmd


@pytest.fixture(scope="session")
def synthetic_fits_path(tmp_path_factory):
    repo_root = Path(__file__).resolve().parents[2]
    tycho_dir = repo_root / "tycho2"
    if not tycho_dir.exists():
        pytest.skip("tycho2 catalog not present")

    astap_cli = os.environ.get("ASTAP_CLI", "astap_cli")
    if not shutil.which(astap_cli):
        pytest.skip("astap_cli not found in PATH")

    astap_db = Path(os.environ.get("ASTAP_DB", str(Path.home() / ".astap")))
    if not astap_db.exists():
        pytest.skip("ASTAP database path not found (set ASTAP_DB)")

    work_dir = tmp_path_factory.mktemp("synthetic_fits")
    # Provide catalog data without writing into the repo.
    (work_dir / "tycho2").symlink_to(tycho_dir)
    hyg_dir = repo_root / "hyg4.2"
    if hyg_dir.exists():
        (work_dir / "hyg4.2").symlink_to(hyg_dir)

    script = repo_root / "scripts" / "gen_catalog_starfield.py"
    result = subprocess.run(
        [sys.executable, str(script)], cwd=work_dir, capture_output=True, text=True
    )
    if result.returncode != 0:
        pytest.skip(f"synthetic generator failed: {result.stderr.strip()}")

    fits_path = work_dir / "synthetic_qhy5iii462_starfield.fits"
    if not fits_path.exists():
        pytest.skip("synthetic FITS not generated")

    return fits_path


@pytest.mark.integration
def test_astap_solve_integration_synthetic(synthetic_fits_path):
    backend = AstapSolverBackend(
        binary=os.environ.get("ASTAP_CLI", "astap_cli"),
        database_path=os.environ.get("ASTAP_DB", str(Path.home() / ".astap")),
    )
    image = Image(
        data=str(synthetic_fits_path),
        width_px=1920,
        height_px=1080,
        timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
        exposure_s=2.0,
        metadata={},
    )
    request = SolveRequest(image=image)
    result = backend.solve(request)
    assert result.success is True
    assert result.ra_rad is not None
    assert result.dec_rad is not None
