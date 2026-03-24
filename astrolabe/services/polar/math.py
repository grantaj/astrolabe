"""Pure geometric functions for polar axis error computation.

No backend imports. No side effects. All angles in radians.
"""

import math

from .types import _CircleFitResult, _PoseObservation

# --- 3D vector helpers (tuples of 3 floats) ---

_Vec3 = tuple[float, float, float]


def _dot(a: _Vec3, b: _Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: _Vec3, b: _Vec3) -> _Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(v: _Vec3) -> float:
    return math.sqrt(_dot(v, v))


def _normalize(v: _Vec3) -> _Vec3:
    n = _norm(v)
    if n < 1e-15:
        raise ValueError("Cannot normalise a zero-length vector")
    return (v[0] / n, v[1] / n, v[2] / n)


def _scale(v: _Vec3, s: float) -> _Vec3:
    return (v[0] * s, v[1] * s, v[2] * s)


def _sub(a: _Vec3, b: _Vec3) -> _Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: _Vec3, b: _Vec3) -> _Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


# --- Coordinate conversions ---


def _radec_to_cart(ra_rad: float, dec_rad: float) -> _Vec3:
    """Convert (RA, Dec) in radians to a Cartesian unit vector."""
    cos_dec = math.cos(dec_rad)
    return (
        cos_dec * math.cos(ra_rad),
        cos_dec * math.sin(ra_rad),
        math.sin(dec_rad),
    )


def _cart_to_radec(v: _Vec3) -> tuple[float, float]:
    """Convert a Cartesian unit vector to (RA, Dec) in radians."""
    dec = math.asin(max(-1.0, min(1.0, v[2])))
    ra = math.atan2(v[1], v[0])
    if ra < 0:
        ra += 2 * math.pi
    return ra, dec


# --- Circle fitting ---


def _fit_circle_spherical(
    points: list[tuple[float, float]],
) -> _CircleFitResult:
    """Fit a small circle to three or more points on the unit sphere.

    For each consecutive pair of points, compute the perpendicular
    bisecting plane (containing all sphere points equidistant from both).
    The pole of the small circle is the intersection of these planes.

    For N=3: two bisecting planes yield a unique line via cross-product;
    the pole is the unit vector along that line.
    For N>3: the overdetermined system is solved via least-squares
    (normal equations augmented with a unit-norm constraint).
    """
    if len(points) < 3:
        raise ValueError(f"Need ≥3 points, got {len(points)}")

    vecs = [_radec_to_cart(ra, dec) for ra, dec in points]

    # Each consecutive pair defines a bisecting-plane normal and offset.
    # Plane equation: n · x = d, where n = (P_{i+1} - P_i) and
    # d = n · midpoint.
    normals: list[_Vec3] = []
    offsets: list[float] = []

    for i in range(len(vecs) - 1):
        p_i = vecs[i]
        p_j = vecs[i + 1]
        n = _sub(p_j, p_i)
        if _norm(n) < 1e-12:
            raise ValueError("Two consecutive points are identical")
        mid = _scale(_add(p_i, p_j), 0.5)
        normals.append(n)
        offsets.append(_dot(n, mid))

    # Also add the pair (last, first) to close the loop — gives an extra
    # constraint that improves numerical stability for N=3 and provides
    # N constraints (instead of N-1) for the least-squares case.
    n_wrap = _sub(vecs[0], vecs[-1])
    if _norm(n_wrap) > 1e-12:
        mid_wrap = _scale(_add(vecs[-1], vecs[0]), 0.5)
        normals.append(n_wrap)
        offsets.append(_dot(n_wrap, mid_wrap))

    if len(normals) < 2:
        raise ValueError("Not enough distinct bisecting planes")

    # For 3 points the cross-product of two plane normals gives the
    # direction of the pole.  For more points use least-squares.
    if len(points) == 3:
        pole_cart = _fit_pole_cross(normals, offsets, vecs)
    else:
        pole_cart = _fit_pole_lstsq(normals, offsets, vecs)

    pole_ra, pole_dec = _cart_to_radec(pole_cart)

    # Radius = mean angular distance from each point to the pole.
    ang_dists = [math.acos(max(-1.0, min(1.0, _dot(pole_cart, v)))) for v in vecs]
    radius = sum(ang_dists) / len(ang_dists)

    # A radius near π/2 means the points lie on a great circle, which
    # is degenerate for small-circle fitting (the pole is ambiguous).
    if abs(radius - math.pi / 2) < math.radians(1.0):
        raise ValueError(
            "Points lie on or near a great circle — cannot fit a small circle"
        )

    # Residual = RMS deviation from the mean radius.
    residual = math.sqrt(sum((d - radius) ** 2 for d in ang_dists) / len(ang_dists))

    return _CircleFitResult(
        pole_ra_rad=pole_ra,
        pole_dec_rad=pole_dec,
        radius_rad=radius,
        residual_rad=residual,
    )


def _fit_pole_cross(
    normals: list[_Vec3],
    offsets: list[float],
    vecs: list[_Vec3],
) -> _Vec3:
    """Find the pole via cross-product of two bisecting-plane normals.

    The pole lies along the intersection line of the two planes.
    We pick the direction consistent with the centroid of the points.
    """
    line_dir = _cross(normals[0], normals[1])
    if _norm(line_dir) < 1e-12:
        raise ValueError("Bisecting planes are parallel — points may be collinear")
    pole = _normalize(line_dir)

    # Choose hemisphere: pole should be on the same side as the points.
    centroid = (
        sum(v[0] for v in vecs) / len(vecs),
        sum(v[1] for v in vecs) / len(vecs),
        sum(v[2] for v in vecs) / len(vecs),
    )
    if _dot(pole, centroid) < 0:
        pole = _scale(pole, -1.0)

    return pole


def _fit_pole_lstsq(
    normals: list[_Vec3],
    offsets: list[float],
    vecs: list[_Vec3],
) -> _Vec3:
    """Find the pole via least-squares for N > 3 points.

    Solves the overdetermined system via normal equations (A^T A x = A^T b).
    """
    ata = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    atb = [0.0, 0.0, 0.0]

    for n, d in zip(normals, offsets):
        for r in range(3):
            for c in range(3):
                ata[r][c] += n[r] * n[c]
            atb[r] += n[r] * d

    pole_cart = _solve_3x3_cramer(ata, atb)
    pole = _normalize(pole_cart)

    centroid = (
        sum(v[0] for v in vecs) / len(vecs),
        sum(v[1] for v in vecs) / len(vecs),
        sum(v[2] for v in vecs) / len(vecs),
    )
    if _dot(pole, centroid) < 0:
        pole = _scale(pole, -1.0)

    return pole


def _solve_3x3_cramer(m: list[list[float]], b: list[float]) -> _Vec3:
    """Solve a 3×3 linear system via Cramer's rule."""

    def _det3(mat: list[list[float]]) -> float:
        return (
            mat[0][0] * (mat[1][1] * mat[2][2] - mat[1][2] * mat[2][1])
            - mat[0][1] * (mat[1][0] * mat[2][2] - mat[1][2] * mat[2][0])
            + mat[0][2] * (mat[1][0] * mat[2][1] - mat[1][1] * mat[2][0])
        )

    det_a = _det3(m)
    if abs(det_a) < 1e-30:
        raise ValueError("Singular matrix in circle fit — points may be collinear")

    results: list[float] = []
    for col in range(3):
        replaced = [row[:] for row in m]
        for row in range(3):
            replaced[row][col] = b[row]
        results.append(_det3(replaced) / det_a)

    return (results[0], results[1], results[2])


# --- Pole-to-error projection ---


def _pole_to_altaz_error(
    pole_ra_rad: float,
    pole_dec_rad: float,
    site_latitude_rad: float,
) -> tuple[float, float]:
    """Compute alt/az correction to move the mount axis to the celestial pole.

    The celestial pole is at (RA=0, Dec=±π/2) depending on hemisphere.
    The fitted pole is the mount's actual rotation axis. The difference,
    projected into the observer's local horizon frame, gives the
    mechanical alt/az adjustment.

    Returns (alt_error_rad, az_error_rad):
        Positive alt_error = raise the polar axis.
        Positive az_error = shift the polar axis east.
    """
    # Determine target pole based on hemisphere
    if site_latitude_rad >= 0:
        target_dec = math.pi / 2
    else:
        target_dec = -math.pi / 2

    target_cart = _radec_to_cart(0.0, target_dec)
    pole_cart = _radec_to_cart(pole_ra_rad, pole_dec_rad)

    # Difference vector in equatorial Cartesian
    diff = _sub(target_cart, pole_cart)

    # Build local horizon frame at the celestial pole as seen from
    # the observer's latitude.  At the pole, the altitude axis points
    # along the meridian (north-south) and the azimuth axis points
    # east-west.
    #
    # The celestial pole is at altitude = site_latitude above the
    # horizon.  We need unit vectors in the "up" (altitude increase)
    # and "east" (azimuth increase) directions at the pole position
    # on the sky.
    #
    # In the equatorial frame with the pole at (0, 0, ±1):
    #   "up" (altitude increase) = toward zenith projected
    #     perpendicular to the pole direction.
    #   "east" = perpendicular to both pole and up.

    # Zenith in equatorial Cartesian (for observer at given latitude,
    # at local sidereal time = 0 for simplicity — the projection only
    # depends on the angular separation, not the absolute RA).
    zenith = _radec_to_cart(0.0, site_latitude_rad)

    # "up" direction at the pole: component of zenith perpendicular to
    # the pole direction.  This is the direction in which raising the
    # mount axis would move it.
    pole_dot_zenith = _dot(target_cart, zenith)
    up_raw = _sub(zenith, _scale(target_cart, pole_dot_zenith))
    up_norm = _norm(up_raw)

    if up_norm < 1e-12:
        # Observer is at the pole — altitude and azimuth are degenerate.
        # Return the total angular error as altitude, zero azimuth.
        total = math.acos(max(-1.0, min(1.0, _dot(target_cart, pole_cart))))
        return total, 0.0

    up = _normalize(up_raw)

    # "east" direction: perpendicular to both pole and up.
    # For northern hemisphere the cross product pole × up points east.
    # For southern hemisphere the sign is flipped (pole is -Z), but
    # the cross product still yields a consistent east direction because
    # both target_cart and up are already hemisphere-aware.
    east = _normalize(_cross(target_cart, up))

    alt_error = _dot(diff, up)
    az_error = _dot(diff, east)

    return alt_error, az_error


# --- Public API ---


def fit_polar_axis(
    poses: list[_PoseObservation],
    site_latitude_rad: float,
) -> tuple[float, float, _CircleFitResult]:
    """Fit the mount's rotation axis from three or more field-centre solves.

    Returns (alt_error_rad, az_error_rad, fit_result).
        Positive alt_error = raise the polar axis.
        Positive az_error = shift the polar axis east.
    """
    if len(poses) < 3:
        raise ValueError(f"Need at least 3 poses for circle fitting, got {len(poses)}")

    points = [(p.ra_rad, p.dec_rad) for p in poses]
    fit = _fit_circle_spherical(points)

    alt_err, az_err = _pole_to_altaz_error(
        fit.pole_ra_rad, fit.pole_dec_rad, site_latitude_rad
    )

    return alt_err, az_err, fit


def correction_confidence(
    fit_result: _CircleFitResult,
    poses: list[_PoseObservation],
) -> float:
    """Estimate confidence in [0.0, 1.0] from fit quality and solve quality.

    Two independent signals are combined:
    - Fit residual: how well the points lie on a circle.
    - Per-pose RMS: how precise each plate solve was.

    Both are mapped through exponential decay so that small values yield
    high confidence and large values yield low confidence.
    """
    # Fit residual contribution: 10 arcsec residual ≈ 50% confidence
    residual_arcsec = math.degrees(fit_result.residual_rad) * 3600
    fit_conf = math.exp(-residual_arcsec / 14.4)

    # Per-solve RMS contribution: mean RMS of 5 arcsec ≈ 50% confidence
    mean_rms = sum(p.rms_arcsec for p in poses) / max(len(poses), 1)
    solve_conf = math.exp(-mean_rms / 7.2)

    # Geometric mean of the two signals
    return math.sqrt(fit_conf * solve_conf)
