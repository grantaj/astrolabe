# Plan: Polar Alignment Service Module

**Date:** 2026-03-01  
**Status:** Layout & Architecture Specification  
**Scope:** Refactor `services/polar.py` → `services/polar/` package with internal structure  
**Breaking Changes:** None

---

## 1. Current State

The polar alignment feature is currently a **stub** in a single flat file:

```
astrolabe/services/polar.py      ← 22 lines: PolarResult dataclass + PolarAlignService with run() raising NotImplementedFeature
```

The CLI (`cli/commands.py:run_polar`) already wires mount, camera, and solver backends into `PolarAlignService(mount, camera, solver)` and calls `service.run(ra_rotation_rad=...)`. The `services/__init__.py` re-exports `PolarAlignService` and `PolarResult`.

---

## 2. Design Rationale: Three-Pose Method

### 2.1 Why not two poses?

The architecture doc (`§5.3`) describes a conceptual two-pose flow: capture/solve at pose A, rotate RA, capture/solve at pose B, compute error. This is geometrically sound in theory — if the commanded RA rotation is mechanically exact, two field-centre solves fully constrain the alt/az correction.

In practice, two poses are insufficient:

- **Gear backlash, periodic error, and flexure** mean the actual RA rotation rarely matches the commanded rotation. The two-pose method assumes the arc length is known; any mechanical deviation feeds directly into the correction.
- **No redundancy.** Two measurements produce two unknowns (alt error, az error) with zero residual. There is nothing left to estimate solution quality — a bad plate solve at either pose silently corrupts the result.
- **Confidence is synthetic.** Without a fit residual, the `confidence` and `residual_arcsec` fields in `PolarResult` can only be estimated from plate-solve RMS, which measures *solve quality*, not *alignment quality*.

### 2.2 Three-pose circle fitting

When the mount rotates in RA, the field centre traces a small circle on the celestial sphere. The centre of that circle is the mount's actual polar axis. Three field-centre solves at three RA positions provide one degree of freedom beyond the minimum needed to fit a circle, which gives:

1. **No dependence on commanded rotation.** The circle fit derives the axis from the geometry of the three points alone. Backlash and periodic error affect where the points land, not the fit itself.
2. **A real fit residual.** The deviation of the three points from the best-fit circle is a direct measure of observation consistency. This maps naturally to `residual_arcsec` and `confidence` in `PolarResult`.
3. **Robustness to a single bad solve.** A failed or inaccurate solve at one pose produces a large fit residual, which the service can detect and report rather than returning a garbage correction.
4. **Extensibility.** The same `fit_polar_axis()` function works with N≥3 poses. Future work could expose a `num_poses` parameter for higher-precision alignment without changing the math layer.

This is consistent with mature implementations (SharpCap, NINA three-point polar alignment, PHD2 drift alignment) that all use three or more samples.

### 2.3 Relationship to `docs/architecture.md §5.3`

The architecture doc describes the *data flow* (capture → solve → rotate → repeat → compute → output). The three-pose method follows the same flow with one additional rotate+capture+solve step. The public interface (`run(ra_rotation_rad) → PolarResult`) is unchanged; `ra_rotation_rad` becomes the rotation step applied twice (A→B, B→C) for a total rotation of `2 × ra_rotation_rad`.

---

## 3. Target Layout

Promote `services/polar.py` → `services/polar/` package. The other services (`goto.py`, `alignment.py`, `guide.py`) remain as flat files — no changes.

```
astrolabe/services/
  __init__.py                    ← UNCHANGED (import path resolves to polar/__init__.py)
  goto.py                        ← unchanged
  alignment.py                   ← unchanged
  guide.py                        ← unchanged
  polar.py                       ← DELETE (replaced by polar/)
  polar/
    __init__.py                  ← re-exports: PolarAlignService, PolarResult
    types.py                     ← PolarResult dataclass (+ internal data types)
    service.py                   ← PolarAlignService class (orchestration)
    math.py                      ← pure polar-alignment geometry / axis-error computation
```

```
tests/services/
  __init__.py                    ← NEW (empty)
  polar/
    __init__.py                  ← NEW (empty)
    test_math.py                 ← unit tests for axis-error math
    test_service.py              ← service-level tests with mocked backends
```

---

## 4. File Specifications

### 4.1 `astrolabe/services/polar/__init__.py`

**Purpose:** Package entry point; re-exports public API.

```python
from .service import PolarAlignService
from .types import PolarResult

__all__ = [
    "PolarAlignService",
    "PolarResult",
]
```

**Rationale:** Follows the `planner/__init__.py` pattern — re-export public names, declare `__all__`. Ensures backward compatibility: `from astrolabe.services.polar import PolarAlignService` still works.

---

### 4.2 `astrolabe/services/polar/types.py`

**Purpose:** Data types for the polar alignment service.

Move `PolarResult` from the current `polar.py` into this file:

```python
from dataclasses import dataclass


@dataclass
class PolarResult:
    alt_correction_arcsec: float | None
    az_correction_arcsec: float | None
    residual_arcsec: float | None
    confidence: float | None
    message: str | None = None
```

**Conformance:**
- Fields match `docs/interfaces.md §3.3` exactly.
- All angular corrections in **arcseconds** (user-facing, per `docs/conventions.md §5`).
- Confidence as float in range [0–1].

**Internal types (module-private, prefixed with `_`):**

```python
@dataclass
class _PoseObservation:
    """Result of a single capture→solve at one RA position."""
    ra_rad: float
    dec_rad: float
    rms_arcsec: float
    timestamp_utc: datetime.datetime


@dataclass
class _CircleFitResult:
    """Result of fitting a small circle to three or more pose observations."""
    pole_ra_rad: float        # RA of fitted rotation axis (ICRS)
    pole_dec_rad: float       # Dec of fitted rotation axis (ICRS)
    radius_rad: float         # angular radius of fitted circle
    residual_rad: float       # RMS deviation of points from fitted circle
```

- `_PoseObservation` captures the plate-solve result at each pose (A, B, C) for consumption by the math layer. Includes `rms_arcsec` from the solver so the confidence estimator has access to per-pose solve quality.
- `_CircleFitResult` is the output of the circle fitting step. The fitted pole direction is the mount's actual rotation axis; comparing it to the celestial pole yields the alt/az correction. The `residual_rad` field measures how well the three points lie on a circle — this is the observation-derived quality metric that maps to `PolarResult.residual_arcsec`.

Neither type is re-exported from `__init__.py`.

---

### 4.3 `astrolabe/services/polar/math.py`

**Purpose:** Pure geometric functions for polar axis error computation via least-squares circle fitting.

**Design invariants:**
- No backend imports.
- No side effects.
- All inputs/outputs in **radians** (internal convention per `docs/conventions.md §2.1`).
- Conversion to arcseconds happens only at the service boundary when constructing `PolarResult`.

**Function signatures:**

#### `fit_polar_axis()`

```python
def fit_polar_axis(
    poses: list[_PoseObservation],
    site_latitude_rad: float,
) -> tuple[float, float, _CircleFitResult]:
    """
    Fit the mount's rotation axis from three or more field-centre solves,
    then compute the polar alignment error.

    When the mount rotates in RA, the field centre traces a small circle
    on the celestial sphere. The centre of that circle is the mount's
    actual rotation axis. Comparing the fitted axis to the celestial pole
    yields the required altitude and azimuth corrections.

    Args:
        poses: Three or more _PoseObservation results at distinct RA
               positions (ICRS). Order does not matter.
        site_latitude_rad: Observer latitude (radians, positive north).

    Returns:
        (alt_error_rad, az_error_rad, fit_result)
        - alt_error_rad: Altitude correction (radians). Positive = raise axis.
        - az_error_rad: Azimuth correction (radians). Positive = shift axis east.
        - fit_result: _CircleFitResult with fitted pole, radius, and residual.

    Raises:
        ValueError: If fewer than 3 poses are provided.

    Algorithm:
    1. Convert each (ra, dec) to a Cartesian unit vector on the celestial sphere.
    2. Call _fit_circle_spherical() to find the pole of the small circle
       through the three (or more) field-centre positions.
    3. The angular radius of the circle is the mean angular distance from
       each point to the fitted pole.
    4. The fit residual is the RMS deviation of each point's angular
       distance from the fitted radius.
    5. Call _pole_to_altaz_error() to project the vector from the celestial
       pole to the fitted pole onto the observer's local horizon frame,
       yielding the alt/az corrections.
    """
```

#### `_fit_circle_spherical()`

```python
def _fit_circle_spherical(
    points: list[tuple[float, float]],
) -> _CircleFitResult:
    """
    Fit a small circle to three or more points on the unit sphere.

    Args:
        points: List of (ra_rad, dec_rad) in ICRS.

    Returns:
        _CircleFitResult with pole direction, radius, and residual.

    Method:
    - Convert each (RA, Dec) to a Cartesian unit vector.
    - For each consecutive pair of points (P_i, P_{i+1}), compute the
      perpendicular bisecting plane: the plane that passes through the
      midpoint of the chord and is normal to the chord direction.
      This plane contains all points on the sphere equidistant from
      P_i and P_{i+1}.
    - The pole of the small circle is the intersection of these
      bisecting planes, normalised to a unit vector.
    - For exactly 3 points, two bisecting planes yield a unique line;
      the pole is the unit vector along that line (direction chosen
      so that dot(pole, point) > 0).
    - For N > 3, the system of N-1 plane equations is overdetermined;
      solve via least-squares (A^T A x = A^T b, a 3x3 symmetric
      system solvable by Cramer's rule).
    - Radius = mean angular distance from each point to the pole.
    - Residual = RMS of (angular_distance - radius) across all points.

    Notes:
    - For exactly 3 points, the fit is exact (residual ≈ 0 up to
      floating-point precision) unless the points are collinear.
    - For N > 3, the least-squares solution minimises the sum of
      squared deviations from the bisecting planes.
    - Implementation uses only stdlib `math` and basic 3D vector
      operations (cross-product, dot-product, normalisation).
    """
```

#### `_pole_to_altaz_error()`

```python
def _pole_to_altaz_error(
    pole_ra_rad: float,
    pole_dec_rad: float,
    site_latitude_rad: float,
) -> tuple[float, float]:
    """
    Compute the alt/az correction needed to move the mount's rotation
    axis from its current direction to the celestial pole.

    Args:
        pole_ra_rad: RA of the fitted rotation axis (ICRS, radians).
        pole_dec_rad: Dec of the fitted rotation axis (ICRS, radians).
        site_latitude_rad: Observer latitude (radians, positive north).

    Returns:
        (alt_error_rad, az_error_rad) — the mechanical adjustment
        required, expressed in the observer's horizon frame.
    """
```

#### `correction_confidence()`

```python
def correction_confidence(
    fit_result: _CircleFitResult,
    poses: list[_PoseObservation],
) -> float:
    """
    Estimate confidence in the polar alignment correction.

    Confidence is derived from two independent signals:
    - fit_result.residual_rad: How well the three points lie on a
      circle. A low residual means the observations are self-consistent.
    - Per-pose rms_arcsec: How precise each individual plate solve was.

    Returns:
        Confidence score in range [0.0, 1.0].
        Low residual + low per-solve RMS → high confidence.
        Large residual or high solve RMS → low confidence.
    """
```

**Function dependency graph:**

```
fit_polar_axis()
├── _fit_circle_spherical()   → _CircleFitResult
├── _pole_to_altaz_error()    → (alt_error_rad, az_error_rad)
└── correction_confidence()   → float (called by service, not by fit_polar_axis)
```

**Constraints:**
- Per `docs/conventions.md §7`: no mount-frame dependency, no wall-clock dependency.
- Per `docs/architecture.md §3.1`: no backend imports.
- All math in radians; unit conversions only at service boundary.
- No external dependencies. Uses only stdlib `math` and basic 3D vector operations (cross-product, dot-product, normalisation).

---

### 4.4 `astrolabe/services/polar/service.py`

**Purpose:** Orchestration of the three-pose polar alignment workflow.

**Class signature:**

```python
from astrolabe.errors import ServiceError
from .types import PolarResult, _PoseObservation
from .math import fit_polar_axis, correction_confidence


class PolarAlignService:
    def __init__(self, mount_backend, camera_backend, solver_backend):
        """
        Initialize the polar alignment service.
        
        Args:
            mount_backend: Mount backend (interface from docs/interfaces.md §2.3).
            camera_backend: Camera backend (interface from docs/interfaces.md §2.1).
            solver_backend: Solver backend (interface from docs/interfaces.md §2.2).
        """
        self._mount = mount_backend
        self._camera = camera_backend
        self._solver = solver_backend

    def run(
        self,
        ra_rotation_rad: float,
        site_latitude_rad: float | None = None,
        exposure_s: float | None = None,
        settle_time_s: float = 2.0,
    ) -> PolarResult:
        """
        Execute the three-pose polar alignment routine.

        The mount is rotated in RA by ra_rotation_rad twice, capturing
        and plate-solving at each of three positions. The three field
        centres are used to fit a small circle on the celestial sphere;
        the centre of that circle is the mount's actual rotation axis.

        Args:
            ra_rotation_rad: RA rotation step between poses (radians).
                Applied twice: A→B and B→C. Total rotation = 2 × step.
            site_latitude_rad: Observer latitude (radians, positive
                north). If None, read from mount backend state; if the
                backend also returns None, raise ServiceError.
            exposure_s: Exposure time in seconds (optional; defaults to
                camera backend default).
            settle_time_s: Seconds to wait after each slew completes
                before capturing. Allows mechanical vibrations to damp.
                Default 2.0 s.

        Returns:
            PolarResult with alt/az corrections in arcseconds, fit
            residual, and confidence estimate. On failure, corrections
            are None with a descriptive message.

        Raises:
            ServiceError: If tracking is not active, or if site latitude
                is unavailable from both the parameter and the mount.

        Flow:
        1. Assert mount is sidereally tracking (required so that ICRS
           coordinates form a proper circle around the mechanical axis).
        2. Resolve site latitude (parameter → mount state → error).
        3. Capture and solve at initial RA position (pose A).
        4. Rotate mount RA axis by ra_rotation_rad; wait settle_time_s.
        5. Capture and solve at second position (pose B).
        6. Rotate mount RA axis by ra_rotation_rad again; wait settle_time_s.
        7. Capture and solve at third position (pose C).
        8. Fit small circle through A, B, C to find rotation axis.
        9. Compare fitted axis to celestial pole → alt/az corrections.
        10. Return corrections in arcseconds + confidence from fit quality.
        """
```

**Internal methods (private):**

| Method | Signature | Responsibility |
|--------|-----------|-----------------|
| `_capture_and_solve()` | `(exposure_s: float \| None) → _PoseObservation` | Capture frame, plate solve, return field centre + RMS + timestamp. Raise `ServiceError` on solve failure. |
| `_rotate_ra()` | `(delta_rad: float, settle_time_s: float) → None` | Get current mount state, compute target RA, call `self._mount.slew_to(...)`, then `time.sleep(settle_time_s)` to let vibrations damp before the next exposure. |
| `_resolve_latitude()` | `(site_latitude_rad: float \| None) → float` | Return the explicit parameter if not None; otherwise read `self._mount.get_state().latitude_rad`; raise `ServiceError` if both are None. |
| `run()` body | (public) | Assert tracking → resolve latitude → Pose A → rotate+settle → Pose B → rotate+settle → Pose C → fit → result. |

**Orchestration sequence diagram:**

```
Service                    Camera       Solver       Mount
  │                          │            │            │
  ├─ assert tracking ──────────────────────────────────►│
  │  get_state().tracking == True ────────────────────►│
  │                                                    │
  ├─ _resolve_latitude(site_latitude_rad)             │
  │  [internal; reads param, mount state if param=None]
  │                                                    │
  ├─ _capture_and_solve() ──►│            │            │
  │  capture(exposure_s) ────►│            │            │
  │  ◄── Image ──────────────┤            │            │
  │  solve(SolveRequest) ──────────────────►            │
  │  ◄── SolveResult (pose A) ────────────┤            │
  │                                                    │
  ├─ _rotate_ra(step, settle_time_s) ────────────────►│
  │  get_state() ────────────────────────────────────►│
  │  slew_to(ra + step, dec) ────────────────────────►│
  │  time.sleep(settle_time_s)                        │
  │                                                    │
  ├─ _capture_and_solve() ──►│            │            │
  │  capture(exposure_s) ────►│            │            │
  │  ◄── Image ──────────────┤            │            │
  │  solve(SolveRequest) ──────────────────►            │
  │  ◄── SolveResult (pose B) ────────────┤            │
  │                                                    │
  ├─ _rotate_ra(step, settle_time_s) ────────────────►│
  │  get_state() ────────────────────────────────────►│
  │  slew_to(ra + step, dec) ────────────────────────►│
  │  time.sleep(settle_time_s)                        │
  │                                                    │
  ├─ _capture_and_solve() ──►│            │            │
  │  capture(exposure_s) ────►│            │            │
  │  ◄── Image ──────────────┤            │            │
  │  solve(SolveRequest) ──────────────────►            │
  │  ◄── SolveResult (pose C) ────────────┤            │
  │                                                    │
  ├─ fit_polar_axis([A, B, C], site_lat)               │
  │  → (alt_error_rad, az_error_rad, fit_result)       │
  │                                                    │
  ├─ correction_confidence(fit_result, [A, B, C])      │
  │  → confidence                                      │
  │                                                    │
  └─ return PolarResult(arcsec conversions)            │
```

**Error handling:**
- Tracking not active → raise `ServiceError` before any capture. Sidereal tracking is required so that ICRS coordinates form a proper circle around the mechanical axis; without it, Earth rotation skews the geometry.
- Site latitude unavailable (parameter is None and mount state returns None) → raise `ServiceError`. The alt/az projection cannot be computed without latitude.
- Solve failure at any pose → return `PolarResult` with all corrections `None` and descriptive message identifying which pose failed.
- Mount communication error → let `BackendError` propagate to CLI layer (per `docs/architecture.md §7`).
- Services decide retry vs. fatal; structured error objects used.
- If `fit_polar_axis` raises `ValueError` (e.g., collinear points), catch and return `PolarResult` with message.

**Configuration:**
- Exposure time sourced from:
  1. `exposure_s` parameter if provided.
  2. `self._camera.capture(...)` uses backend default if `None`.
- Site latitude sourced from (in order):
  1. `site_latitude_rad` parameter if not None.
  2. Mount backend state (`self._mount.get_state().latitude_rad`) if available.
  3. Raise `ServiceError` if both are None. Not all mount drivers report site latitude; the explicit parameter provides a reliable fallback from CLI `--lat` or global config.
- Settle time:
  - `settle_time_s` parameter (default 2.0 s). Applied after each slew, before the next capture. Mechanical mounts wobble when they stop; this prevents star trailing in the plate solve exposure.

---

## 5. Test Structure

### 5.1 `tests/services/__init__.py`

Empty marker file (package declaration).

```python
```

### 5.2 `tests/services/polar/__init__.py`

Empty marker file (package declaration).

```python
```

### 5.3 `tests/services/polar/test_math.py`

**Purpose:** Unit tests for circle fitting and axis error computation. No mocking required — all functions are pure.

**Test cases:**

| Test | Scenario | Assertion |
|------|----------|-----------|
| `test_perfect_alignment_zero_error` | Three poses on a small circle centred exactly on the celestial pole | `alt_error ≈ 0`, `az_error ≈ 0`, residual ≈ 0 |
| `test_known_alt_error` | Three poses on a circle whose pole is offset in altitude from the celestial pole | alt_error matches expected offset; az_error ≈ 0 |
| `test_known_az_error` | Three poses on a circle whose pole is offset in azimuth | az_error matches expected offset; alt_error ≈ 0 |
| `test_combined_alt_az_error` | Circle pole offset in both alt and az | Both corrections have expected magnitude and sign |
| `test_fit_circle_three_points_exact` | Three points generated from a known circle | Fitted pole matches generating pole; residual ≈ 0 |
| `test_fit_circle_four_points_residual` | Four points, one deliberately perturbed off-circle | Fitted pole close to true pole; residual > 0 |
| `test_fit_circle_collinear_raises` | Three collinear points (great circle) | `ValueError` raised |
| `test_confidence_low_residual_low_rms` | Clean fit + clean solves | Confidence near 1.0 |
| `test_confidence_high_residual` | Large fit residual | Confidence well below 1.0 |
| `test_confidence_high_solve_rms` | Low fit residual but high per-solve RMS | Confidence reduced |
| `test_units_radians` | Known geometry with calculable result | Output in radians (not degrees/arcsec) |
| `test_minimum_three_poses_required` | Pass two poses to `fit_polar_axis` | `ValueError` raised |
| `test_hemisphere_independence` | Repeat known-error test at southern latitude | Same magnitude, appropriate sign |

**Example test structure:**

```python
import math
import datetime
import pytest
from astrolabe.services.polar.math import fit_polar_axis, correction_confidence, _fit_circle_spherical
from astrolabe.services.polar.types import _PoseObservation, _CircleFitResult


def _make_pose(ra_deg, dec_deg, rms=1.0, minutes_offset=0):
    """Helper to build a _PoseObservation from degree values."""
    return _PoseObservation(
        ra_rad=math.radians(ra_deg),
        dec_rad=math.radians(dec_deg),
        rms_arcsec=rms,
        timestamp_utc=datetime.datetime(
            2026, 3, 1, 0, minutes_offset, 0,
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
        # Rotate a point at angular distance `radius` from the pole
        # around the pole axis by `angle`.
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
        poses.append(_make_pose(math.degrees(ra), math.degrees(dec), minutes_offset=i * 5))
    return poses


def test_perfect_alignment_zero_error():
    """Three poses on a circle centred on the celestial pole → no correction needed."""
    # Pole at (ra=0, dec=90) = celestial north pole
    poses = _generate_circle_poses(pole_ra_deg=0.0, pole_dec_deg=90.0, radius_deg=20.0)
    site_lat_rad = math.radians(45.0)

    alt_err, az_err, fit = fit_polar_axis(poses, site_lat_rad)

    assert abs(alt_err) < math.radians(0.01)  # < 0.01° error
    assert abs(az_err) < math.radians(0.01)
    assert fit.residual_rad < 1e-6


def test_known_alt_error():
    """Circle pole offset 1° in altitude from celestial pole."""
    # Offset pole: dec = 89° instead of 90° (1° altitude error at lat 45°)
    poses = _generate_circle_poses(pole_ra_deg=0.0, pole_dec_deg=89.0, radius_deg=20.0)
    site_lat_rad = math.radians(45.0)

    alt_err, az_err, fit = fit_polar_axis(poses, site_lat_rad)

    assert abs(alt_err) > math.radians(0.5)   # significant altitude correction
    assert fit.residual_rad < 1e-6             # three points → exact fit


def test_minimum_three_poses_required():
    """Fewer than 3 poses raises ValueError."""
    poses = [_make_pose(10.0, 45.0), _make_pose(25.0, 45.0)]
    with pytest.raises(ValueError):
        fit_polar_axis(poses, math.radians(45.0))


def test_fit_circle_three_points_exact():
    """Three points generated from a known circle → exact fit."""
    pole_ra_deg, pole_dec_deg, radius_deg = 45.0, 80.0, 15.0
    poses = _generate_circle_poses(pole_ra_deg, pole_dec_deg, radius_deg)
    points = [(p.ra_rad, p.dec_rad) for p in poses]

    result = _fit_circle_spherical(points)

    assert abs(math.degrees(result.pole_dec_rad) - pole_dec_deg) < 0.01
    assert result.residual_rad < 1e-6


def test_confidence_high_residual():
    """Large fit residual → low confidence."""
    fit = _CircleFitResult(
        pole_ra_rad=0.0,
        pole_dec_rad=math.radians(89.0),
        radius_rad=math.radians(20.0),
        residual_rad=math.radians(0.5),  # 0.5° residual — poor fit
    )
    poses = [_make_pose(10.0, 45.0, rms=1.0) for _ in range(3)]

    conf = correction_confidence(fit, poses)
    assert conf < 0.5
```

### 5.4 `tests/services/polar/test_service.py`

**Purpose:** Service-level tests with mocked backends. Follows pattern from `tests/mount/test_indi_mount.py`.

**Test cases:**

| Test | Setup | Expectation |
|------|-------|-------------|
| `test_run_happy_path` | Mock camera captures, solver returns three SolveResults, mount slews twice | `PolarResult` has non-None corrections in arcseconds |
| `test_run_solve_failure_pose_a` | Solver returns `success=False` on first solve | Graceful `PolarResult` with message, all corrections `None`; no slew attempted |
| `test_run_solve_failure_pose_b` | Solver succeeds pose A, fails pose B after first slew | Graceful `PolarResult` with message; only one slew occurs |
| `test_run_solve_failure_pose_c` | Solver succeeds poses A and B, fails pose C | Graceful `PolarResult` with message |
| `test_run_backend_call_order` | Mock all backends | Verify call order: capture→solve→slew→sleep→capture→solve→slew→sleep→capture→solve |
| `test_result_units_arcseconds` | Happy path | Verify corrections in `PolarResult` are arcseconds (not radians) |
| `test_exposure_parameter_passed` | Pass `exposure_s=5.0` to `run()` | Verify all three camera captures called with correct exposure |
| `test_exposure_default_if_none` | Pass `exposure_s=None` to `run()` | Camera capture called without forcing exposure |
| `test_collinear_points_handled` | Solver returns three results that are collinear | `PolarResult` with corrections `None` and descriptive message |
| `test_tracking_not_active_raises` | `mount.get_state().tracking == False` | `ServiceError` raised before any capture or slew |
| `test_latitude_from_parameter` | Pass explicit `site_latitude_rad` | Mount state latitude ignored; explicit value used |
| `test_latitude_from_mount_state` | `site_latitude_rad=None`, mount state has latitude | Latitude read from mount state |
| `test_latitude_missing_raises` | `site_latitude_rad=None`, mount state latitude is None | `ServiceError` raised |
| `test_settle_time_respected` | Pass `settle_time_s=3.0` | `time.sleep(3.0)` called after each slew, before each capture |

**Example test structure:**

```python
import math
import pytest
from unittest.mock import MagicMock, call, patch
from astrolabe.services.polar import PolarAlignService, PolarResult
from astrolabe.errors import ServiceError
from astrolabe.solver.types import SolveResult, Image
import datetime


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


@pytest.fixture
def mock_backends():
    """Fixture providing mocked mount, camera, and solver backends."""
    mount = MagicMock()
    camera = MagicMock()
    solver = MagicMock()

    camera.capture.return_value = Image(
        data=b"fake_fits_data",
        width_px=800,
        height_px=600,
        timestamp_utc=datetime.datetime(2026, 3, 1, 0, 0, 0, tzinfo=datetime.timezone.utc),
        exposure_s=2.0,
        metadata={},
    )

    mount.get_state.return_value = MagicMock(
        connected=True,
        ra_rad=math.radians(10.0),
        dec_rad=math.radians(45.0),
        tracking=True,
        slewing=False,
        latitude_rad=_SITE_LAT_RAD,
    )

    return mount, camera, solver


def test_run_happy_path(mock_backends):
    """Successful three-pose polar alignment."""
    mount, camera, solver = mock_backends

    # Three successful solves at three RA positions (15° step)
    solver.solve.side_effect = [
        _make_solve_result(10.0, 45.0),   # pose A
        _make_solve_result(25.0, 45.0),   # pose B (A + 15°)
        _make_solve_result(40.0, 45.0),   # pose C (B + 15°)
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
    assert result.message is None or "success" in result.message.lower()

    # Three captures, three solves, two slews
    assert camera.capture.call_count == 3
    assert solver.solve.call_count == 3
    assert mount.slew_to.call_count == 2


def test_run_solve_failure_pose_a(mock_backends):
    """First solve fails; service returns early without slewing."""
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
    assert "pose" in result.message.lower() or "solve" in result.message.lower()

    # Should not have attempted any slew after failing pose A
    mount.slew_to.assert_not_called()


def test_run_solve_failure_pose_c(mock_backends):
    """Third solve fails after two successful poses and two slews."""
    mount, camera, solver = mock_backends
    solver.solve.side_effect = [
        _make_solve_result(10.0, 45.0),   # pose A — ok
        _make_solve_result(25.0, 45.0),   # pose B — ok
        _FAILED_SOLVE,                    # pose C — fail
    ]

    service = PolarAlignService(mount, camera, solver)
    result = service.run(
        ra_rotation_rad=math.radians(15.0),
        site_latitude_rad=_SITE_LAT_RAD,
    )

    assert result.alt_correction_arcsec is None
    assert result.az_correction_arcsec is None
    assert result.message is not None


@patch("astrolabe.services.polar.service.time.sleep")
def test_run_backend_call_order(mock_sleep, mock_backends):
    """Verify the three-pose orchestration calls backends in the correct sequence."""
    mount, camera, solver = mock_backends
    solver.solve.side_effect = [
        _make_solve_result(10.0, 45.0),
        _make_solve_result(25.0, 45.0),
        _make_solve_result(40.0, 45.0),
    ]

    # Use a shared log to track interleaved call order across backends
    call_log = []
    camera.capture.side_effect = lambda *a, **kw: (
        call_log.append("capture"),
        camera.capture.return_value,
    )[-1]
    solve_iter = iter(solver.solve.side_effect)
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
        "capture", "solve",                    # pose A
        "slew", "sleep", "capture", "solve",   # pose B
        "slew", "sleep", "capture", "solve",   # pose C
    ]


def test_tracking_not_active_raises(mock_backends):
    """Service refuses to run if mount is not sidereally tracking."""
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


def test_latitude_from_mount_state(mock_backends):
    """Latitude falls back to mount state when parameter is None."""
    mount, camera, solver = mock_backends
    solver.solve.side_effect = [
        _make_solve_result(10.0, 45.0),
        _make_solve_result(25.0, 45.0),
        _make_solve_result(40.0, 45.0),
    ]

    service = PolarAlignService(mount, camera, solver)
    result = service.run(
        ra_rotation_rad=math.radians(15.0),
        site_latitude_rad=None,  # should read from mount state
    )

    assert result.alt_correction_arcsec is not None


def test_latitude_missing_raises(mock_backends):
    """ServiceError when latitude is unavailable from both param and mount."""
    mount, camera, solver = mock_backends
    mount.get_state.return_value.latitude_rad = None

    service = PolarAlignService(mount, camera, solver)
    with pytest.raises(ServiceError):
        service.run(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=None,
        )
```

---

## 6. No Breaking Changes

| Area | Breaking? | Detail |
|------|-----------|--------|
| Public API | **No** | Same class names, same fields, same `run()` signature. |
| Import path `astrolabe.services.PolarAlignService` | **No** | Re-exported from `services/__init__.py` as before. |
| Import path `astrolabe.services.polar.PolarAlignService` | **No** | Package `__init__.py` makes this valid. |
| CLI interface | **No** | `astrolabe polar --ra-rotation-deg 15` unchanged. |
| Adding `exposure_s` param | **No** | Optional parameter with default `None`. |
| Adding `site_latitude_rad` param | **No** | Optional parameter with default `None` (falls back to mount state). |
| Adding `settle_time_s` param | **No** | Optional parameter with default `2.0`. |
| `ra_rotation_rad` semantics | **No** | Was unused (stub raised `NotImplementedFeature`). Now defined as the step size between poses (applied twice, total = 2×step). No existing caller depends on the old meaning. |
| Internal APIs | **N/A** | Prefixed `_` types are module-private; not public contract. |

---

## 7. Wiring Changes (Existing Files)

### 7.1 `astrolabe/services/__init__.py`

**Change required:** None (atomic refactor).

```python
from .polar import PolarAlignService, PolarResult  # ← no change; resolves to polar/__init__.py
```

Once the flat `polar.py` is deleted and the `polar/` package is in place, Python's import system resolves this transparently.

### 7.2 `astrolabe/cli/commands.py`

**Change required:** None.

The import `from astrolabe.services import PolarAlignService` resolves through `services/__init__.py`, which re-exports from the new package. The `run_polar()` function and call to `service.run(...)` remain valid.

### 7.3 `astrolabe/cli/main.py`

**Change required:** None.

Parser definition for `polar` subcommand stays as-is.

---

## 8. Execution Plan

### Phase 1: Create new package structure

1. Create directory `astrolabe/services/polar/`.
2. Create `astrolabe/services/polar/__init__.py` with re-exports.
3. Create `astrolabe/services/polar/types.py` with `PolarResult`, `_PoseObservation`, and `_CircleFitResult`.
4. Create `astrolabe/services/polar/math.py` with `fit_polar_axis()`, `_fit_circle_spherical()`, `_pole_to_altaz_error()`, and `correction_confidence()`.
5. Create `astrolabe/services/polar/service.py` with `PolarAlignService` class.

### Phase 2: Replace flat file

6. **Atomically** delete `astrolabe/services/polar.py`.

### Phase 3: Create test infrastructure

7. Create `tests/services/__init__.py` (empty).
8. Create `tests/services/polar/__init__.py` (empty).
9. Create `tests/services/polar/test_math.py` with unit tests.
10. Create `tests/services/polar/test_service.py` with service tests.

### Phase 4: Validation

11. Run `pytest tests/services/polar/` to verify test execution.
12. Run `pytest` (full suite) to ensure no import regressions.
13. Verify CLI still works:
    - `astrolabe polar --ra-rotation-deg 15 --json` returns JSON envelope with `"not_implemented"` error (as before).
    - `astrolabe polar --ra-rotation-deg 15` returns stderr message (as before).

---

## 9. Summary

| Aspect | Count |
|--------|-------|
| New files | 8 |
| Deleted files | 1 |
| Modified files | 0 |
| New test files | 2 |
| New internal types | 2 (`_PoseObservation`, `_CircleFitResult`) |
| New public types | 0 (only `PolarResult`, already existed) |
| Breaking changes | 0 |

**Total impact:** Low-risk refactor with no public API changes. All imports resolve correctly post-migration. The three-pose circle-fitting method provides a real fit residual for confidence estimation, robustness to mechanical error, and extensibility to N>3 poses. Test infrastructure established for future implementation.

