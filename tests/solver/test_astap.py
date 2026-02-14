import pytest
from astrolabe.solver.astap import AstapSolverBackend
from astrolabe.solver.types import Image, SolveRequest
import datetime
from unittest.mock import patch

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
        metadata={}
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
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        request = SolveRequest(image=sample_image)
        result = backend.solve(request)
        assert result.success is True
        assert result.message.startswith("ASTAP solve succeeded")
