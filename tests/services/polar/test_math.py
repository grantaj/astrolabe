import math
import datetime

import pytest

from astrolabe.services.polar.math import (
    fit_polar_axis,
    correction_confidence,
    _fit_circle_spherical,
)
from astrolabe.services.polar.types import _PoseObservation, _CircleFitResult


def _make_pose(ra_deg, dec_deg, rms=1.0, minutes_offset=0):
    """Helper to build a _PoseObservation from degree values."""
    return _PoseObservation(
        ra_rad=math.radians(ra_deg),
        dec_rad=math.radians(dec_deg),
        rms_arcsec=rms,
        timestamp_utc=datetime.datetime(
            2026,
            3,
            1,
            0,
            minutes_offset,
            0,
            tzinfo=datetime.timezone.utc,
        ),
    )


def _generate_circle_poses(pole_ra_deg, pole_dec_deg, radius_deg, n=3):
    """Generate n poses equally spaced on a small circle with given pole and radius."""
    pole_ra = math.radians(pole_ra_deg)
    pole_dec = math.radians(pole_dec_deg)
    radius = math.radians(radius_deg)
    poses = []
    for i in range(n):
        angle = 2 * math.pi * i / n
        dec = math.asin(
            math.sin(pole_dec) * math.cos(radius)
            + math.cos(pole_dec) * math.sin(radius) * math.cos(angle)
        )
        dra = math.atan2(
            math.sin(radius) * math.sin(angle),
            math.cos(pole_dec) * math.cos(radius)
            - math.sin(pole_dec) * math.sin(radius) * math.cos(angle),
        )
        ra = pole_ra + dra
        poses.append(
            _make_pose(math.degrees(ra), math.degrees(dec), minutes_offset=i * 5)
        )
    return poses


class TestFitPolarAxis:
    def test_perfect_alignment_zero_error(self):
        """Three poses centred on the celestial pole → no correction needed."""
        poses = _generate_circle_poses(0.0, 90.0, 20.0)
        site_lat = math.radians(45.0)

        alt_err, az_err, fit = fit_polar_axis(poses, site_lat)

        assert abs(alt_err) < math.radians(0.01)
        assert abs(az_err) < math.radians(0.01)
        assert fit.residual_rad < 1e-6

    def test_known_alt_error(self):
        """Circle pole offset 1° in altitude from celestial pole."""
        # Pole at dec=89° instead of 90°: 1° altitude error
        poses = _generate_circle_poses(0.0, 89.0, 20.0)
        site_lat = math.radians(45.0)

        alt_err, az_err, fit = fit_polar_axis(poses, site_lat)

        assert abs(alt_err) > math.radians(0.5)
        assert fit.residual_rad < 1e-6

    def test_known_az_error(self):
        """Circle pole offset in azimuth from celestial pole."""
        # Pole at (RA=90°, Dec=89.5°) — mostly an azimuth offset
        poses = _generate_circle_poses(90.0, 89.5, 20.0)
        site_lat = math.radians(45.0)

        alt_err, az_err, fit = fit_polar_axis(poses, site_lat)

        assert abs(az_err) > math.radians(0.1)
        assert fit.residual_rad < 1e-6

    def test_combined_alt_az_error(self):
        """Circle pole offset in both alt and az."""
        # Pole at (RA=45°, Dec=88°) — offset in both dimensions
        poses = _generate_circle_poses(45.0, 88.0, 20.0)
        site_lat = math.radians(45.0)

        alt_err, az_err, fit = fit_polar_axis(poses, site_lat)

        # Both corrections should be significant
        total_err = math.sqrt(alt_err**2 + az_err**2)
        assert total_err > math.radians(1.0)
        assert fit.residual_rad < 1e-6

    def test_minimum_three_poses_required(self):
        """Fewer than 3 poses raises ValueError."""
        poses = [_make_pose(10.0, 45.0), _make_pose(25.0, 45.0)]
        with pytest.raises(ValueError, match="at least 3"):
            fit_polar_axis(poses, math.radians(45.0))

    def test_units_radians(self):
        """Output is in radians, not degrees or arcseconds."""
        poses = _generate_circle_poses(0.0, 89.0, 20.0)
        site_lat = math.radians(45.0)

        alt_err, az_err, fit = fit_polar_axis(poses, site_lat)

        # A 1° error should be ~0.017 rad, not ~1.0 (degrees) or ~3600 (arcsec)
        assert abs(alt_err) < 0.1
        assert abs(alt_err) > 0.001

    def test_hemisphere_independence(self):
        """Southern hemisphere: same magnitude, appropriate sign."""
        # Northern: pole at dec=89°
        n_poses = _generate_circle_poses(0.0, 89.0, 20.0)
        n_alt, n_az, _ = fit_polar_axis(n_poses, math.radians(45.0))

        # Southern: pole at dec=-89°
        s_poses = _generate_circle_poses(0.0, -89.0, 20.0)
        s_alt, s_az, _ = fit_polar_axis(s_poses, math.radians(-45.0))

        # Magnitudes should be comparable
        assert abs(abs(n_alt) - abs(s_alt)) < math.radians(0.1)


class TestFitCircleSpherical:
    def test_three_points_exact(self):
        """Three points from a known circle → exact fit."""
        pole_ra_deg, pole_dec_deg, radius_deg = 45.0, 80.0, 15.0
        poses = _generate_circle_poses(pole_ra_deg, pole_dec_deg, radius_deg)
        points = [(p.ra_rad, p.dec_rad) for p in poses]

        result = _fit_circle_spherical(points)

        assert abs(math.degrees(result.pole_dec_rad) - pole_dec_deg) < 0.01
        assert abs(math.degrees(result.radius_rad) - radius_deg) < 0.01
        assert result.residual_rad < 1e-6

    def test_four_points_residual(self):
        """Four points, one perturbed off-circle → non-zero residual."""
        pole_ra_deg, pole_dec_deg, radius_deg = 45.0, 80.0, 15.0
        poses = _generate_circle_poses(pole_ra_deg, pole_dec_deg, radius_deg, n=4)

        # Perturb the last point
        points = [(p.ra_rad, p.dec_rad) for p in poses]
        perturbed_dec = points[3][1] + math.radians(0.5)
        points[3] = (points[3][0], perturbed_dec)

        result = _fit_circle_spherical(points)

        # Pole should still be close to true pole
        assert abs(math.degrees(result.pole_dec_rad) - pole_dec_deg) < 1.0
        # But residual should be non-zero
        assert result.residual_rad > 1e-4

    def test_collinear_raises(self):
        """Three points on a great circle (radius ≈ 90°) → ValueError."""
        # Three points along the celestial equator — they lie on a great
        # circle (radius = 90°), which is degenerate for small-circle fitting.
        points = [
            (math.radians(0.0), 0.0),
            (math.radians(1.0), 0.0),
            (math.radians(2.0), 0.0),
        ]
        with pytest.raises(ValueError, match="great circle"):
            _fit_circle_spherical(points)


class TestCorrectionConfidence:
    def test_low_residual_low_rms(self):
        """Clean fit + clean solves → high confidence."""
        fit = _CircleFitResult(
            pole_ra_rad=0.0,
            pole_dec_rad=math.radians(90.0),
            radius_rad=math.radians(20.0),
            residual_rad=math.radians(0.001),
        )
        poses = [_make_pose(10.0, 45.0, rms=0.5) for _ in range(3)]

        conf = correction_confidence(fit, poses)
        assert conf > 0.8

    def test_high_residual(self):
        """Large fit residual → low confidence."""
        fit = _CircleFitResult(
            pole_ra_rad=0.0,
            pole_dec_rad=math.radians(89.0),
            radius_rad=math.radians(20.0),
            residual_rad=math.radians(0.5),
        )
        poses = [_make_pose(10.0, 45.0, rms=1.0) for _ in range(3)]

        conf = correction_confidence(fit, poses)
        assert conf < 0.5

    def test_high_solve_rms(self):
        """Low fit residual but high per-solve RMS → reduced confidence."""
        fit = _CircleFitResult(
            pole_ra_rad=0.0,
            pole_dec_rad=math.radians(90.0),
            radius_rad=math.radians(20.0),
            residual_rad=math.radians(0.001),
        )
        # High per-solve RMS
        poses = [_make_pose(10.0, 45.0, rms=20.0) for _ in range(3)]

        conf = correction_confidence(fit, poses)
        # Should be noticeably lower than the clean case
        assert conf < 0.7
