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


MIN_POSES = 4
_MISSING_RMS_PENALTY_ARCSEC = 10.0


def _fit_circle_spherical(
    points: list[tuple[float, float]],
) -> _CircleFitResult:
    """Fit a small circle to four or more points on the unit sphere.

    Every point on a small circle with pole ``p`` and angular radius ``r``
    satisfies ``p · v_i = cos(r)``.  Treating ``(p, c = cos r)`` as four
    unknowns yields a homogeneous-ish linear system that we solve by
    least squares (fixing the dominant component of ``p`` via the
    observation centroid to avoid the singular minimum-norm solution).

    A minimum of four points is required: three points uniquely
    determine a small circle on the sphere, so the residual is
    structurally zero and conveys no quality information.
    """
    if len(points) < MIN_POSES:
        raise ValueError(f"Need ≥{MIN_POSES} points, got {len(points)}")

    vecs = [_radec_to_cart(ra, dec) for ra, dec in points]

    for i in range(len(vecs)):
        for j in range(i + 1, len(vecs)):
            if _norm(_sub(vecs[i], vecs[j])) < 1e-12:
                raise ValueError("Two points are identical")

    pole_cart = _fit_pole_lstsq(vecs)
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


def _fit_pole_lstsq(vecs: list[_Vec3]) -> _Vec3:
    """Fit the small-circle pole by least-squares over all observations.

    Solves the linear system ``p · v_i = c`` for all ``i`` where
    ``(p_x, p_y, p_z, c)`` are the unknowns.  To avoid the trivial
    minimum-norm solution we fix the dominant component of ``p`` (chosen
    from the centroid of the observations) and solve the resulting
    3-unknown overdetermined system via normal equations.
    """
    centroid = (
        sum(v[0] for v in vecs) / len(vecs),
        sum(v[1] for v in vecs) / len(vecs),
        sum(v[2] for v in vecs) / len(vecs),
    )

    i_max = max(range(3), key=lambda k: abs(centroid[k]))
    sign = 1.0 if centroid[i_max] >= 0 else -1.0
    other = [k for k in range(3) if k != i_max]

    # Equation per observation: p[other[0]] * v[other[0]]
    #                         + p[other[1]] * v[other[1]]
    #                         - c
    #                         = -sign * v[i_max]
    ata = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    atb = [0.0, 0.0, 0.0]
    for v in vecs:
        row = (v[other[0]], v[other[1]], -1.0)
        rhs = -sign * v[i_max]
        for r in range(3):
            for c in range(3):
                ata[r][c] += row[r] * row[c]
            atb[r] += row[r] * rhs

    p_o0, p_o1, _cos_r = _solve_3x3_cramer(ata, atb)
    pole = [0.0, 0.0, 0.0]
    pole[i_max] = sign
    pole[other[0]] = p_o0
    pole[other[1]] = p_o1
    pole_unit = _normalize((pole[0], pole[1], pole[2]))

    # Defensive: if the fixed-axis sign guess disagrees with the
    # observations' centroid (possible when the arc is tangential to the
    # pole's dominant axis), flip into the observed hemisphere.
    centroid = (
        sum(v[0] for v in vecs) / len(vecs),
        sum(v[1] for v in vecs) / len(vecs),
        sum(v[2] for v in vecs) / len(vecs),
    )
    if _dot(pole_unit, centroid) < 0:
        pole_unit = _scale(pole_unit, -1.0)
    return pole_unit


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
        raise ValueError(
            "Singular matrix in circle fit — points may be collinear or "
            "lie on a great circle"
        )

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
    if len(poses) < MIN_POSES:
        raise ValueError(
            f"Need at least {MIN_POSES} poses for circle fitting, got {len(poses)}"
        )

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

    Two independent signals are combined via geometric mean:
    - Fit residual: how well the points lie on a circle.
    - Per-pose RMS: how precise each plate solve was.

    Missing ``rms_arcsec`` values are replaced with a conservative
    penalty (``_MISSING_RMS_PENALTY_ARCSEC``) rather than omitted, so
    that absent data cannot inflate the reported confidence.
    """
    residual_arcsec = math.degrees(fit_result.residual_rad) * 3600
    fit_conf = math.exp(-residual_arcsec / 14.4)

    rms_values = [
        p.rms_arcsec if p.rms_arcsec is not None else _MISSING_RMS_PENALTY_ARCSEC
        for p in poses
    ]
    mean_rms = sum(rms_values) / max(len(rms_values), 1)
    solve_conf = math.exp(-mean_rms / 7.2)

    return math.sqrt(fit_conf * solve_conf)
