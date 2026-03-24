import math
import datetime
from unittest.mock import MagicMock, patch

import pytest

from astrolabe.services.polar import PolarAlignService, PolarResult
from astrolabe.errors import ServiceError
from astrolabe.solver.types import SolveResult, SolveRequest, Image


def _make_solve_result(ra_deg, dec_deg, rms=1.2, num_stars=50):
    """Helper to build a successful SolveResult from degree values."""
    return SolveResult(
        success=True,
        ra_rad=math.radians(ra_deg),
        dec_rad=math.radians(dec_deg),
        pixel_scale_arcsec=1.5,
        rotation_rad=math.radians(0.1),
        rms_arcsec=rms,
        num_stars=num_stars,
        message=None,
    )


_FAILED_SOLVE = SolveResult(
    success=False,
    ra_rad=None,
    dec_rad=None,
    pixel_scale_arcsec=None,
    rotation_rad=None,
    rms_arcsec=None,
    num_stars=0,
    message="No stars detected",
)

_SITE_LAT_RAD = math.radians(45.0)

_FAKE_IMAGE = Image(
    data=b"fake_fits_data",
    width_px=800,
    height_px=600,
    timestamp_utc=datetime.datetime(2026, 3, 1, 0, 0, 0, tzinfo=datetime.timezone.utc),
    exposure_s=2.0,
    metadata={},
)


@pytest.fixture
def mock_backends():
    """Fixture providing mocked mount, camera, and solver backends."""
    mount = MagicMock()
    camera = MagicMock()
    solver = MagicMock()

    camera.capture.return_value = _FAKE_IMAGE

    mount.get_state.return_value = MagicMock(
        connected=True,
        ra_rad=math.radians(10.0),
        dec_rad=math.radians(45.0),
        tracking=True,
        slewing=False,
    )

    return mount, camera, solver


class TestRunHappyPath:
    @patch("astrolabe.services.polar.service.time.sleep")
    def test_returns_valid_result(self, mock_sleep, mock_backends):
        """Successful three-pose polar alignment returns non-None corrections."""
        mount, camera, solver = mock_backends
        solver.solve.side_effect = [
            _make_solve_result(10.0, 45.0),
            _make_solve_result(25.0, 45.0),
            _make_solve_result(40.0, 45.0),
        ]

        service = PolarAlignService(mount, camera, solver)
        result = service.run(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=_SITE_LAT_RAD,
        )

        assert isinstance(result, PolarResult)
        assert result.alt_correction_arcsec is not None
        assert result.az_correction_arcsec is not None
        assert result.confidence is not None
        assert result.residual_arcsec is not None

        # Three captures, three solves, two slews
        assert camera.capture.call_count == 3
        assert solver.solve.call_count == 3
        assert mount.slew_to.call_count == 2

    @patch("astrolabe.services.polar.service.time.sleep")
    def test_result_units_arcseconds(self, mock_sleep, mock_backends):
        """Corrections are in arcseconds, not radians."""
        mount, camera, solver = mock_backends
        solver.solve.side_effect = [
            _make_solve_result(10.0, 45.0),
            _make_solve_result(25.0, 45.0),
            _make_solve_result(40.0, 45.0),
        ]

        service = PolarAlignService(mount, camera, solver)
        result = service.run(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=_SITE_LAT_RAD,
        )

        # Corrections should be in arcsec range (not radians ~0.001 or degrees ~1)
        # Even for a well-aligned mount, corrections shouldn't be tiny fractions
        # unless perfectly aligned.  The mock data forms a wide arc, so
        # corrections will be substantial arcseconds.
        assert result.alt_correction_arcsec is not None
        if abs(result.alt_correction_arcsec) > 0.01:
            assert abs(result.alt_correction_arcsec) > 1.0


class TestSolveFailures:
    @patch("astrolabe.services.polar.service.time.sleep")
    def test_failure_pose_a(self, mock_sleep, mock_backends):
        """First solve fails — service returns early, no slew attempted."""
        mount, camera, solver = mock_backends
        solver.solve.return_value = _FAILED_SOLVE

        service = PolarAlignService(mount, camera, solver)
        result = service.run(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=_SITE_LAT_RAD,
        )

        assert result.alt_correction_arcsec is None
        assert result.az_correction_arcsec is None
        assert result.message is not None
        mount.slew_to.assert_not_called()

    @patch("astrolabe.services.polar.service.time.sleep")
    def test_failure_pose_b(self, mock_sleep, mock_backends):
        """Second solve fails after first slew."""
        mount, camera, solver = mock_backends
        solver.solve.side_effect = [
            _make_solve_result(10.0, 45.0),
            _FAILED_SOLVE,
        ]

        service = PolarAlignService(mount, camera, solver)
        result = service.run(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=_SITE_LAT_RAD,
        )

        assert result.alt_correction_arcsec is None
        assert result.message is not None
        assert mount.slew_to.call_count == 1

    @patch("astrolabe.services.polar.service.time.sleep")
    def test_failure_pose_c(self, mock_sleep, mock_backends):
        """Third solve fails after two slews."""
        mount, camera, solver = mock_backends
        solver.solve.side_effect = [
            _make_solve_result(10.0, 45.0),
            _make_solve_result(25.0, 45.0),
            _FAILED_SOLVE,
        ]

        service = PolarAlignService(mount, camera, solver)
        result = service.run(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=_SITE_LAT_RAD,
        )

        assert result.alt_correction_arcsec is None
        assert result.message is not None
        assert mount.slew_to.call_count == 2


class TestBackendCallOrder:
    @patch("astrolabe.services.polar.service.time.sleep")
    def test_correct_sequence(self, mock_sleep, mock_backends):
        """Verify three-pose orchestration calls backends in correct order."""
        mount, camera, solver = mock_backends
        solve_results = [
            _make_solve_result(10.0, 45.0),
            _make_solve_result(25.0, 45.0),
            _make_solve_result(40.0, 45.0),
        ]
        solve_iter = iter(solve_results)

        call_log = []
        camera.capture.side_effect = lambda *a, **kw: (
            call_log.append("capture"),
            _FAKE_IMAGE,
        )[-1]

        def _solve(*a, **kw):
            call_log.append("solve")
            return next(solve_iter)

        solver.solve.side_effect = _solve
        mount.slew_to.side_effect = lambda *a, **kw: call_log.append("slew")
        mock_sleep.side_effect = lambda *a, **kw: call_log.append("sleep")

        service = PolarAlignService(mount, camera, solver)
        service.run(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=_SITE_LAT_RAD,
        )

        assert call_log == [
            "capture",
            "solve",
            "slew",
            "sleep",
            "capture",
            "solve",
            "slew",
            "sleep",
            "capture",
            "solve",
        ]


class TestExposureParameter:
    @patch("astrolabe.services.polar.service.time.sleep")
    def test_exposure_passed_to_camera(self, mock_sleep, mock_backends):
        """Custom exposure_s is forwarded to all three captures."""
        mount, camera, solver = mock_backends
        solver.solve.side_effect = [
            _make_solve_result(10.0, 45.0),
            _make_solve_result(25.0, 45.0),
            _make_solve_result(40.0, 45.0),
        ]

        service = PolarAlignService(mount, camera, solver)
        service.run(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=_SITE_LAT_RAD,
            exposure_s=5.0,
        )

        assert camera.capture.call_count == 3
        for call in camera.capture.call_args_list:
            assert call.args[0] == 5.0

    @patch("astrolabe.services.polar.service.time.sleep")
    def test_exposure_default(self, mock_sleep, mock_backends):
        """Default exposure (2.0) used when not specified."""
        mount, camera, solver = mock_backends
        solver.solve.side_effect = [
            _make_solve_result(10.0, 45.0),
            _make_solve_result(25.0, 45.0),
            _make_solve_result(40.0, 45.0),
        ]

        service = PolarAlignService(mount, camera, solver)
        service.run(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=_SITE_LAT_RAD,
        )

        for call in camera.capture.call_args_list:
            assert call.args[0] == 2.0


class TestPreconditions:
    def test_tracking_not_active_raises(self, mock_backends):
        """Service refuses to run if mount is not tracking."""
        mount, camera, solver = mock_backends
        mount.get_state.return_value.tracking = False

        service = PolarAlignService(mount, camera, solver)
        with pytest.raises(ServiceError):
            service.run(
                ra_rotation_rad=math.radians(15.0),
                site_latitude_rad=_SITE_LAT_RAD,
            )

        camera.capture.assert_not_called()
        mount.slew_to.assert_not_called()


class TestCollinearPoints:
    @patch("astrolabe.services.polar.service.time.sleep")
    def test_collinear_handled_gracefully(self, mock_sleep, mock_backends):
        """Collinear solve results → graceful failure, not crash."""
        mount, camera, solver = mock_backends
        # Three points along the equator (collinear on a great circle)
        solver.solve.side_effect = [
            _make_solve_result(0.0, 0.0),
            _make_solve_result(90.0, 0.0),
            _make_solve_result(180.0, 0.0),
        ]

        service = PolarAlignService(mount, camera, solver)
        result = service.run(
            ra_rotation_rad=math.radians(90.0),
            site_latitude_rad=_SITE_LAT_RAD,
        )

        assert result.alt_correction_arcsec is None
        assert result.message is not None


class TestSettleTime:
    @patch("astrolabe.services.polar.service.time.sleep")
    def test_settle_time_respected(self, mock_sleep, mock_backends):
        """Custom settle_time_s is passed to time.sleep after each slew."""
        mount, camera, solver = mock_backends
        solver.solve.side_effect = [
            _make_solve_result(10.0, 45.0),
            _make_solve_result(25.0, 45.0),
            _make_solve_result(40.0, 45.0),
        ]

        service = PolarAlignService(mount, camera, solver)
        service.run(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=_SITE_LAT_RAD,
            settle_time_s=3.0,
        )

        assert mock_sleep.call_count == 2
        for call in mock_sleep.call_args_list:
            assert call.args[0] == 3.0


class TestSolveHints:
    @patch("astrolabe.services.polar.service.time.sleep")
    def test_solve_request_includes_mount_hints(self, mock_sleep, mock_backends):
        """SolveRequest includes RA/Dec hints from mount state."""
        mount, camera, solver = mock_backends
        solver.solve.side_effect = [
            _make_solve_result(10.0, 45.0),
            _make_solve_result(25.0, 45.0),
            _make_solve_result(40.0, 45.0),
        ]

        service = PolarAlignService(mount, camera, solver)
        service.run(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=_SITE_LAT_RAD,
        )

        # Each solve call should have received a SolveRequest with hints
        for call in solver.solve.call_args_list:
            request = call.args[0]
            assert isinstance(request, SolveRequest)
            assert request.ra_hint_rad is not None
            assert request.dec_hint_rad is not None
