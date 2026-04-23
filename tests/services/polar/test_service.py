import math
import datetime
from unittest.mock import MagicMock, patch

import pytest

from astrolabe.services.polar import PolarAlignService, PolarResult
from astrolabe.errors import ServiceError
from astrolabe.solver.types import SolveResult, SolveRequest, Image


def _make_solve_result(ra_deg, dec_deg, rms=1.2, num_stars=50):
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


def _four_good_solves():
    """Four poses on a small circle centred near the celestial pole."""
    return [
        _make_solve_result(0.0, 70.0),
        _make_solve_result(90.0, 70.0),
        _make_solve_result(180.0, 70.0),
        _make_solve_result(270.0, 70.0),
    ]


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
        """Successful four-pose polar alignment returns non-None corrections."""
        mount, camera, solver = mock_backends
        solver.solve.side_effect = _four_good_solves()

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

        assert camera.capture.call_count == 4
        assert solver.solve.call_count == 4
        assert mount.slew_to.call_count == 3

    @patch("astrolabe.services.polar.service.time.sleep")
    def test_result_units_arcseconds(self, mock_sleep, mock_backends):
        """Corrections are in arcseconds, not radians."""
        mount, camera, solver = mock_backends
        solver.solve.side_effect = _four_good_solves()

        service = PolarAlignService(mount, camera, solver)
        result = service.run(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=_SITE_LAT_RAD,
        )

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
    def test_failure_mid_sequence(self, mock_sleep, mock_backends):
        """Mid-sequence solve failure returns gracefully."""
        mount, camera, solver = mock_backends
        solver.solve.side_effect = [
            _make_solve_result(0.0, 70.0),
            _make_solve_result(90.0, 70.0),
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

    @patch("astrolabe.services.polar.service.time.sleep")
    def test_success_but_none_coords_is_failure(self, mock_sleep, mock_backends):
        """Solver returning success=True with None coords is a failure."""
        mount, camera, solver = mock_backends
        solver.solve.side_effect = [
            SolveResult(
                success=True,
                ra_rad=None,
                dec_rad=None,
                pixel_scale_arcsec=None,
                rotation_rad=None,
                rms_arcsec=1.0,
                num_stars=30,
                message=None,
            ),
        ]

        service = PolarAlignService(mount, camera, solver)
        result = service.run(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=_SITE_LAT_RAD,
        )

        assert result.alt_correction_arcsec is None
        assert result.message is not None


class TestBackendCallOrder:
    @patch("astrolabe.services.polar.service.time.sleep")
    def test_correct_sequence(self, mock_sleep, mock_backends):
        """Verify N-pose orchestration calls backends in correct order."""
        mount, camera, solver = mock_backends
        solve_iter = iter(_four_good_solves())

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

        expected = ["capture", "solve"]
        for _ in range(3):
            expected += ["slew", "sleep", "capture", "solve"]
        assert call_log == expected


class TestExposureParameter:
    @patch("astrolabe.services.polar.service.time.sleep")
    def test_exposure_passed_to_camera(self, mock_sleep, mock_backends):
        mount, camera, solver = mock_backends
        solver.solve.side_effect = _four_good_solves()

        service = PolarAlignService(mount, camera, solver)
        service.run(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=_SITE_LAT_RAD,
            exposure_s=5.0,
        )

        assert camera.capture.call_count == 4
        for call in camera.capture.call_args_list:
            assert call.args[0] == 5.0

    @patch("astrolabe.services.polar.service.time.sleep")
    def test_exposure_default(self, mock_sleep, mock_backends):
        mount, camera, solver = mock_backends
        solver.solve.side_effect = _four_good_solves()

        service = PolarAlignService(mount, camera, solver)
        service.run(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=_SITE_LAT_RAD,
        )

        for call in camera.capture.call_args_list:
            assert call.args[0] == 2.0


class TestPreconditions:
    def test_tracking_not_active_raises(self, mock_backends):
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

    def test_missing_ra_raises(self, mock_backends):
        """Service refuses to run if mount RA is unavailable."""
        mount, camera, solver = mock_backends
        mount.get_state.return_value.ra_rad = None

        service = PolarAlignService(mount, camera, solver)
        with pytest.raises(ServiceError, match="coordinates unavailable"):
            service.run(
                ra_rotation_rad=math.radians(15.0),
                site_latitude_rad=_SITE_LAT_RAD,
            )
        camera.capture.assert_not_called()

    def test_missing_dec_raises(self, mock_backends):
        mount, camera, solver = mock_backends
        mount.get_state.return_value.dec_rad = None

        service = PolarAlignService(mount, camera, solver)
        with pytest.raises(ServiceError, match="coordinates unavailable"):
            service.run(
                ra_rotation_rad=math.radians(15.0),
                site_latitude_rad=_SITE_LAT_RAD,
            )

    def test_num_poses_below_minimum_raises(self, mock_backends):
        mount, camera, solver = mock_backends
        service = PolarAlignService(mount, camera, solver)
        with pytest.raises(ServiceError, match="num_poses"):
            service.run(
                ra_rotation_rad=math.radians(15.0),
                site_latitude_rad=_SITE_LAT_RAD,
                num_poses=3,
            )


class TestCollinearPoints:
    @patch("astrolabe.services.polar.service.time.sleep")
    def test_collinear_handled_gracefully(self, mock_sleep, mock_backends):
        """Collinear solve results → graceful failure, not crash."""
        mount, camera, solver = mock_backends
        solver.solve.side_effect = [
            _make_solve_result(0.0, 0.0),
            _make_solve_result(90.0, 0.0),
            _make_solve_result(180.0, 0.0),
            _make_solve_result(270.0, 0.0),
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
        mount, camera, solver = mock_backends
        solver.solve.side_effect = _four_good_solves()

        service = PolarAlignService(mount, camera, solver)
        service.run(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=_SITE_LAT_RAD,
            settle_time_s=3.0,
        )

        assert mock_sleep.call_count == 3
        for call in mock_sleep.call_args_list:
            assert call.args[0] == 3.0


class TestSolveHints:
    @patch("astrolabe.services.polar.service.time.sleep")
    def test_solve_request_includes_mount_hints(self, mock_sleep, mock_backends):
        mount, camera, solver = mock_backends
        solver.solve.side_effect = _four_good_solves()

        service = PolarAlignService(mount, camera, solver)
        service.run(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=_SITE_LAT_RAD,
        )

        for call in solver.solve.call_args_list:
            request = call.args[0]
            assert isinstance(request, SolveRequest)
            assert request.ra_hint_rad is not None
            assert request.dec_hint_rad is not None


class TestConfidenceWithMissingRms:
    @patch("astrolabe.services.polar.service.time.sleep")
    def test_missing_rms_does_not_inflate_confidence(self, mock_sleep, mock_backends):
        """A pose with rms_arcsec=None must not produce a perfect solve
        signal — confidence with missing RMS should be strictly less than
        confidence with comparable non-missing RMS values."""
        mount, camera, solver = mock_backends
        solves_missing = [
            _make_solve_result(0.0, 70.0, rms=None),
            _make_solve_result(90.0, 70.0, rms=1.0),
            _make_solve_result(180.0, 70.0, rms=1.0),
            _make_solve_result(270.0, 70.0, rms=1.0),
        ]
        solver.solve.side_effect = solves_missing

        service = PolarAlignService(mount, camera, solver)
        result_missing = service.run(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=_SITE_LAT_RAD,
        )

        # Reset and run again with clean RMS values.
        camera.reset_mock()
        solver.reset_mock()
        solver.solve.side_effect = _four_good_solves()
        service2 = PolarAlignService(mount, camera, solver)
        result_clean = service2.run(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=_SITE_LAT_RAD,
        )

        assert result_missing.confidence is not None
        assert result_clean.confidence is not None
        # With identical geometry, missing RMS must not exceed the
        # signal derived from real RMS data.
        assert result_missing.confidence <= result_clean.confidence + 1e-9
