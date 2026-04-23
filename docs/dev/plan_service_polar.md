# Plan: Polar Alignment Service Module

**Date:** 2026-03-01
**Updated:** 2026-04-23
**Status:** Implemented (revised after PR #29 review)
**Scope:** Refactor `services/polar.py` → `services/polar/` package with internal structure
**Breaking Changes:** None to public API; the service now requires N≥4 poses (default 4) instead of exactly 3.

---

## 0. Revision log (post PR-review)

Changes made in response to review feedback on PR #29:

- **Minimum pose count raised from 3 to 4.** Three non-degenerate points on the sphere uniquely determine a small circle, so the fit residual was structurally zero regardless of method. Four or more points make the residual a meaningful signal of pose-to-pose consistency.
- **Single least-squares fitter.** The N=3 cross-product specialisation (`_fit_pole_cross`) has been removed. `_fit_circle_spherical()` now always solves `p · v_i = cos(r)` by least-squares over all observations, fixing the dominant component of `p` via the centroid to avoid the singular minimum-norm solution.
- **Order-invariant fit.** The new formulation depends only on the set of observations, not on their order.
- **Service hardening.** Mount coordinate availability (`state.ra_rad`, `state.dec_rad`) is validated before any capture and before each slew. Solver results with `success=True` but missing `ra_rad`/`dec_rad` are treated as failures.
- **Honest confidence.** Missing `rms_arcsec` values are replaced with a conservative penalty (10 arcsec) rather than `0.0`, so absent data cannot inflate confidence. `_PoseObservation.rms_arcsec` is now `float | None`.
- **Configurable pose count.** `PolarAlignService.run(num_poses=4)` and CLI flag `--num-poses`.
- **CLI error propagation.** `astrolabe polar` now returns exit code 1 and `ok=false` when the service reports a failure via `PolarResult.message`; the JSON envelope carries a `polar_failed` error block.

---

## 1. Previous State

The polar alignment feature was a **stub** in a single flat file:

```
astrolabe/services/polar.py      ← 21 lines: PolarResult dataclass + PolarAlignService with run() raising NotImplementedFeature
```

The CLI (`cli/commands.py:run_polar`) already wired mount, camera, and solver backends into `PolarAlignService(mount, camera, solver)` and called `service.run(ra_rotation_rad=...)`. The `services/__init__.py` re-exported `PolarAlignService` and `PolarResult`.

---

## 2. Design Rationale: Three-Pose Method

### 2.1 Why not two poses?

The architecture doc (section 5.3) describes a conceptual two-pose flow: capture/solve at pose A, rotate RA, capture/solve at pose B, compute error. This is geometrically sound in theory — if the commanded RA rotation is mechanically exact, two field-centre solves fully constrain the alt/az correction.

In practice, two poses are insufficient:

- **Gear backlash, periodic error, and flexure** mean the actual RA rotation rarely matches the commanded rotation. The two-pose method assumes the arc length is known; any mechanical deviation feeds directly into the correction.
- **No redundancy.** Two measurements produce two unknowns (alt error, az error) with zero residual. There is nothing left to estimate solution quality — a bad plate solve at either pose silently corrupts the result.
- **Confidence is synthetic.** Without a fit residual, the `confidence` and `residual_arcsec` fields in `PolarResult` can only be estimated from plate-solve RMS, which measures *solve quality*, not *alignment quality*.

### 2.2 Three-pose circle fitting

When the mount rotates in RA, the field centre traces a small circle on the celestial sphere. The centre of that circle is the mount's actual polar axis. Three field-centre solves at three RA positions provide one degree of freedom beyond the minimum needed to fit a circle, which gives:

1. **No dependence on commanded rotation.** The circle fit derives the axis from the geometry of the three points alone. Backlash and periodic error affect where the points land, not the fit itself.
2. **A real fit residual.** The deviation of the three points from the best-fit circle is a direct measure of observation consistency. This maps naturally to `residual_arcsec` and `confidence` in `PolarResult`.
3. **Robustness to a single bad solve.** A failed or inaccurate solve at one pose produces a large fit residual, which the service can detect and report rather than returning a garbage correction.
4. **Extensibility.** The same `fit_polar_axis()` function works for any N≥4 poses. The service exposes `num_poses` so operators can trade time for precision.

This is consistent with mature implementations (SharpCap, NINA three-point polar alignment, PHD2 drift alignment) that all use three or more samples.

### 2.3 Relationship to `docs/architecture.md section 5.3`

The architecture doc describes the *data flow* (capture → solve → rotate → repeat → compute → output). The N-pose method follows the same flow, repeating rotate+capture+solve until `num_poses` observations have been collected. The public interface (`run(ra_rotation_rad, site_latitude_rad, ..., num_poses=4) → PolarResult`) extends the stub signature; `ra_rotation_rad` is applied between each successive pose, for a total rotation of `(num_poses − 1) × ra_rotation_rad`.

---

## 3. Target Layout

Promote `services/polar.py` → `services/polar/` package. The other services (`goto.py`, `alignment.py`, `guide.py`) remain as flat files — no changes.

```
astrolabe/services/
  __init__.py                    ← UNCHANGED (import path resolves to polar/__init__.py)
  goto.py                        ← unchanged
  alignment.py                   ← unchanged
  guide.py                       ← unchanged
  polar/
    __init__.py                  ← re-exports: PolarAlignService, PolarResult
    types.py                     ← PolarResult dataclass (+ internal data types)
    service.py                   ← PolarAlignService class (orchestration)
    math.py                      ← pure polar-alignment geometry / axis-error computation
```

```
tests/services/
  __init__.py                    ← empty marker
  polar/
    __init__.py                  ← empty marker
    test_math.py                 ← unit tests for axis-error math (13 tests)
    test_service.py              ← service-level tests with mocked backends (12 tests)
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

```python
from dataclasses import dataclass
import datetime


@dataclass
class PolarResult:
    alt_correction_arcsec: float | None
    az_correction_arcsec: float | None
    residual_arcsec: float | None
    confidence: float | None
    message: str | None = None
```

**Conformance:**
- Fields match `docs/interfaces.md section 3.3` exactly.
- All angular corrections in **arcseconds** (user-facing, per `docs/conventions.md section 5`).
- Confidence as float in range [0–1].

**Internal types (module-private, prefixed with `_`):**

```python
@dataclass
class _PoseObservation:
    """Result of a single capture→solve at one RA position."""
    ra_rad: float
    dec_rad: float
    rms_arcsec: float | None
    timestamp_utc: datetime.datetime


@dataclass
class _CircleFitResult:
    """Result of fitting a small circle to four or more pose observations."""
    pole_ra_rad: float
    pole_dec_rad: float
    radius_rad: float
    residual_rad: float
```

- `_PoseObservation` captures the plate-solve result at each pose (A, B, C) for consumption by the math layer. Includes `rms_arcsec` from the solver so the confidence estimator has access to per-pose solve quality.
- `_CircleFitResult` is the output of the circle fitting step. The fitted pole direction is the mount's actual rotation axis; comparing it to the celestial pole yields the alt/az correction. The `residual_rad` field measures how well the three points lie on a circle — this is the observation-derived quality metric that maps to `PolarResult.residual_arcsec`.

Neither type is re-exported from `__init__.py`.

---

### 4.3 `astrolabe/services/polar/math.py`

**Purpose:** Pure geometric functions for polar axis error computation via circle fitting on the unit sphere.

**Design invariants:**
- No backend imports.
- No side effects.
- All inputs/outputs in **radians** (internal convention per `docs/conventions.md section 2.1`).
- Conversion to arcseconds happens only at the service boundary when constructing `PolarResult`.
- No external dependencies. Uses only stdlib `math` and basic 3D vector operations (cross-product, dot-product, normalisation) implemented as helpers on `tuple[float, float, float]`.

**3D vector helpers:**

The module defines a `_Vec3 = tuple[float, float, float]` type alias and the following private helpers: `_dot`, `_cross`, `_norm`, `_normalize`, `_scale`, `_sub`, `_add`, `_radec_to_cart`, `_cart_to_radec`. These operate on 3-tuples without any external dependency.

**Function signatures:**

#### `fit_polar_axis()`

```python
def fit_polar_axis(
    poses: list[_PoseObservation],
    site_latitude_rad: float,
) -> tuple[float, float, _CircleFitResult]:
```

Top-level entry point. Validates ≥4 poses, delegates to `_fit_circle_spherical()` for the circle fit, then calls `_pole_to_altaz_error()` for the alt/az projection.

Returns `(alt_error_rad, az_error_rad, fit_result)`. Raises `ValueError` if fewer than 4 poses.

#### `_fit_circle_spherical()`

```python
def _fit_circle_spherical(
    points: list[tuple[float, float]],
) -> _CircleFitResult:
```

Fits a small circle to four or more points on the unit sphere by least-squares.

**Algorithm (as implemented, revised post-review):**

1. Convert each (RA, Dec) to a Cartesian unit vector `v_i`.
2. Every point on a small circle with pole `p` and angular radius `r` satisfies `p · v_i = cos(r)`. Treat `(p_x, p_y, p_z, c = cos r)` as four unknowns.
3. Compute the centroid of `{v_i}`; fix the component of `p` corresponding to the dominant axis of the centroid (sign taken from the centroid). This avoids the trivial minimum-norm solution that the naive bisecting-plane formulation produces when all observations lie on the unit sphere (where every plane passes through the origin).
4. Solve the remaining overdetermined 3-unknown linear system (two free components of `p` plus `c`) via normal equations and Cramer's rule.
5. Normalise `p` to the unit sphere.
6. Radius = mean angular distance from each observation to `p`.
7. **Great-circle detection:** if the fitted radius is within 1° of π/2, raise `ValueError`.
8. Residual = RMS of (angular_distance − radius) across all points.

The fit is order-invariant and exclusively least-squares; the previous N=3 cross-product specialisation has been removed. Four poses are the minimum that produces a non-zero residual for inconsistent observations.

#### `_fit_pole_lstsq()`

```python
def _fit_pole_lstsq(vecs: list[_Vec3]) -> _Vec3:
```

Fits the pole by least-squares over all observations. Raises `ValueError` (via `_solve_3x3_cramer`) when the system is singular (collinear points / great-circle geometry).

#### `_solve_3x3_cramer()`

```python
def _solve_3x3_cramer(
    m: list[list[float]], b: list[float]
) -> _Vec3:
```

Solves a 3×3 linear system via Cramer's rule. Raises `ValueError` if the determinant is near zero (singular system).

#### `_pole_to_altaz_error()`

```python
def _pole_to_altaz_error(
    pole_ra_rad: float,
    pole_dec_rad: float,
    site_latitude_rad: float,
) -> tuple[float, float]:
```

Projects the vector from the celestial pole to the fitted pole onto the observer's local horizon frame. Determines the target pole based on hemisphere (north: Dec=+π/2, south: Dec=-π/2). Constructs "up" (altitude) and "east" (azimuth) basis vectors at the pole using the observer's zenith direction projected perpendicular to the pole. Handles the degenerate case of an observer at the geographic pole.

Returns `(alt_error_rad, az_error_rad)`. Positive alt = raise axis. Positive az = shift east.

#### `correction_confidence()`

```python
def correction_confidence(
    fit_result: _CircleFitResult,
    poses: list[_PoseObservation],
) -> float:
```

Estimates confidence in [0.0, 1.0] by combining two independent signals via exponential decay and geometric mean:
- **Fit residual:** converted to arcseconds, mapped through `exp(-residual_arcsec / 14.4)` so that 10 arcsec residual ≈ 50% confidence.
- **Per-solve RMS:** mean across poses, mapped through `exp(-mean_rms / 7.2)` so that 5 arcsec mean RMS ≈ 50% confidence.

Final confidence = `sqrt(fit_conf * solve_conf)`.

**Function dependency graph:**

```
fit_polar_axis()
├── _fit_circle_spherical()
│   └── _fit_pole_lstsq()     (least-squares, all N≥4)
│       └── _solve_3x3_cramer()
├── _pole_to_altaz_error()
└── (correction_confidence() is called by service, not by fit_polar_axis)
```

**Constraints:**
- Per `docs/conventions.md section 7`: no mount-frame dependency, no wall-clock dependency.
- Per `docs/architecture.md section 3.1`: no backend imports.
- All math in radians; unit conversions only at service boundary.
- No external dependencies. Uses only stdlib `math` and basic 3D vector operations.

---

### 4.4 `astrolabe/services/polar/service.py`

**Purpose:** Orchestration of the N-pose polar alignment workflow (N≥4, default 4).

**Class signature:**

```python
import math
import time
import datetime

from astrolabe.errors import ServiceError
from astrolabe.solver.types import SolveRequest

from .math import correction_confidence, fit_polar_axis
from .types import PolarResult, _PoseObservation

_RAD_TO_ARCSEC = 180.0 / math.pi * 3600.0


class PolarAlignService:
    def __init__(self, mount_backend, camera_backend, solver_backend):
        self._mount = mount_backend
        self._camera = camera_backend
        self._solver = solver_backend

    def run(
        self,
        ra_rotation_rad: float,
        site_latitude_rad: float,
        exposure_s: float = 2.0,
        settle_time_s: float = 2.0,
    ) -> PolarResult:
```

**Key design decisions (deviations from original plan):**

1. **`site_latitude_rad` is a required parameter** (not `Optional`). The `MountState` dataclass does not have a `latitude_rad` field, so the plan's mount-state fallback was not implementable. The `_resolve_latitude()` private method was removed entirely.
2. **`exposure_s` defaults to `2.0`** (not `None`). `CameraBackend.capture()` requires `exposure_s` as a positional argument, so passing `None` would raise `TypeError`.
3. **`_capture_and_solve()` returns `None` on solve failure** instead of raising `ServiceError`. The `run()` method checks for `None` and returns a graceful `PolarResult` with a descriptive message. This keeps the control flow flat.
4. **A static `_fail()` helper** constructs the failure `PolarResult` to avoid repetition.

**Internal methods (private):**

| Method | Signature | Responsibility |
|--------|-----------|-----------------|
| `_capture_and_solve()` | `(exposure_s: float) → _PoseObservation \| None` | Get mount state for RA/Dec hints, capture frame, build `SolveRequest` with hints, plate solve, return field centre + RMS + timestamp. Return `None` on solve failure. |
| `_rotate_ra()` | `(delta_rad: float, settle_time_s: float) → None` | Get current mount state, compute target RA, call `self._mount.slew_to(...)`, then `time.sleep(settle_time_s)` to let vibrations damp before the next exposure. |
| `_fail()` | `(message: str) → PolarResult` | Static method returning a `PolarResult` with all corrections `None` and the given message. |

**Orchestration sequence diagram:**

```
Service                    Camera       Solver       Mount
  │                          │            │            │
  ├─ assert tracking ──────────────────────────────────►│
  │  get_state().tracking == True ────────────────────►│
  │                                                    │
  ├─ _capture_and_solve() ──►│            │            │
  │  get_state() [for hints] ──────────────────────────►│
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
  │  get_state() [for hints] ──────────────────────────►│
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
  │  get_state() [for hints] ──────────────────────────►│
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
- Solve failure at any pose → return `PolarResult` with all corrections `None` and descriptive message identifying which pose failed (e.g., "Plate solve failed at pose A"). No slews are attempted after a failed pose.
- Mount communication error → let `BackendError` propagate to CLI layer (per `docs/architecture.md section 7`).
- If `fit_polar_axis` raises `ValueError` (e.g., great-circle/collinear points), catch and return `PolarResult` with message.

**Configuration:**
- Exposure time: `exposure_s` parameter (default 2.0 s). Passed directly to `self._camera.capture(exposure_s)`.
- Site latitude: `site_latitude_rad` parameter (required). No mount-state fallback — `MountState` does not have a `latitude_rad` field.
- Settle time: `settle_time_s` parameter (default 2.0 s). Applied after each slew, before the next capture. Mechanical mounts wobble when they stop; this prevents star trailing in the plate solve exposure.

---

## 5. Test Structure

### 5.1 `tests/services/__init__.py`

Empty marker file (package declaration).

### 5.2 `tests/services/polar/__init__.py`

Empty marker file (package declaration).

### 5.3 `tests/services/polar/test_math.py`

**Purpose:** Unit tests for circle fitting and axis error computation. No mocking required — all functions are pure.

**Test cases (13 tests in 3 classes):**

| Class | Test | Scenario | Assertion |
|-------|------|----------|-----------|
| `TestFitPolarAxis` | `test_perfect_alignment_zero_error` | Three poses on a small circle centred exactly on the celestial pole | `alt_error ≈ 0`, `az_error ≈ 0`, residual ≈ 0 |
| | `test_known_alt_error` | Three poses on a circle whose pole is offset 1° in altitude from the celestial pole | alt_error > 0.5°; residual ≈ 0 |
| | `test_known_az_error` | Three poses on a circle whose pole is at (RA=90°, Dec=89.5°) | az_error > 0.1°; residual ≈ 0 |
| | `test_combined_alt_az_error` | Circle pole offset in both alt and az (RA=45°, Dec=88°) | total error > 1° |
| | `test_minimum_four_poses_required` | Pass three poses to `fit_polar_axis` | `ValueError` raised (match "at least 4") |
| | `test_units_radians` | Known 1° offset geometry | Output between 0.001 and 0.1 (radians, not degrees/arcsec) |
| | `test_hemisphere_independence` | Repeat 1° offset test at southern latitude (Dec=-89°, lat=-45°) | Same magnitude as northern case (within 0.1°) |
| `TestFitCircleSpherical` | `test_three_points_exact` | Three points generated from known circle (pole=45°,80°, radius=15°) | Fitted pole matches; residual ≈ 0 |
| | `test_four_points_residual` | Four points, one perturbed 0.5° off-circle | Fitted pole within 1°; residual > 1e-4 |
| | `test_collinear_raises` | Three points along celestial equator (great circle) | `ValueError` raised (match "great circle") |
| `TestCorrectionConfidence` | `test_low_residual_low_rms` | Clean fit (0.001° residual) + clean solves (0.5 arcsec RMS) | Confidence > 0.8 |
| | `test_high_residual` | 0.5° fit residual | Confidence < 0.5 |
| | `test_high_solve_rms` | Low residual but 20 arcsec per-solve RMS | Confidence < 0.7 |

**Test helpers:**
- `_make_pose(ra_deg, dec_deg, rms, minutes_offset)` — builds a `_PoseObservation` from degree values.
- `_generate_circle_poses(pole_ra_deg, pole_dec_deg, radius_deg, n)` — generates n poses equally spaced on a small circle with given pole and radius using spherical geometry.

### 5.4 `tests/services/polar/test_service.py`

**Purpose:** Service-level tests with mocked backends. Follows pattern from `tests/mount/test_indi_mount.py`.

**Test cases (12 tests in 7 classes):**

| Class | Test | Setup | Expectation |
|-------|------|-------|-------------|
| `TestRunHappyPath` | `test_returns_valid_result` | Mock camera captures, solver returns three SolveResults, mount slews twice | `PolarResult` has non-None corrections; 3 captures, 3 solves, 2 slews |
| | `test_result_units_arcseconds` | Happy path | Corrections are arcseconds (> 1.0 if non-trivial) |
| `TestSolveFailures` | `test_failure_pose_a` | Solver returns `success=False` on first solve | Graceful `PolarResult` with message; no slew attempted |
| | `test_failure_pose_b` | Solver succeeds pose A, fails pose B | Graceful result; exactly one slew |
| | `test_failure_pose_c` | Solver succeeds poses A and B, fails pose C | Graceful result; exactly two slews |
| `TestBackendCallOrder` | `test_correct_sequence` | Mock all backends with call logging | Exact order: capture→solve→slew→sleep→capture→solve→slew→sleep→capture→solve |
| `TestExposureParameter` | `test_exposure_passed_to_camera` | Pass `exposure_s=5.0` | All three captures called with 5.0 |
| | `test_exposure_default` | Default `exposure_s` | All three captures called with 2.0 |
| `TestPreconditions` | `test_tracking_not_active_raises` | `mount.get_state().tracking == False` | `ServiceError` raised; no capture or slew |
| `TestCollinearPoints` | `test_collinear_handled_gracefully` | Solver returns three equator points (great circle) | `PolarResult` with corrections `None` and message |
| `TestSettleTime` | `test_settle_time_respected` | Pass `settle_time_s=3.0` | `time.sleep(3.0)` called exactly twice |
| `TestSolveHints` | `test_solve_request_includes_mount_hints` | Happy path | Each `SolveRequest` has non-None `ra_hint_rad` and `dec_hint_rad` |

**Test infrastructure:**
- `_make_solve_result(ra_deg, dec_deg, rms, num_stars)` — helper for successful `SolveResult`.
- `_FAILED_SOLVE` — module-level constant for a failed solve.
- `_FAKE_IMAGE` — module-level constant `Image` for camera mock return.
- `mock_backends` — pytest fixture returning `(mount, camera, solver)` MagicMocks with sane defaults (tracking=True, connected=True, etc.). Note: mount mock does **not** include `latitude_rad` since `MountState` does not have this field.

---

## 6. No Breaking Changes

| Area | Breaking? | Detail |
|------|-----------|--------|
| Public API | **No** | Same class names, same `PolarResult` fields. |
| Import path `astrolabe.services.PolarAlignService` | **No** | Re-exported from `services/__init__.py` as before. |
| Import path `astrolabe.services.polar.PolarAlignService` | **No** | Package `__init__.py` makes this valid. |
| `run()` signature change | **No** | Was a stub raising `NotImplementedFeature`. Now accepts `ra_rotation_rad` (same), `site_latitude_rad` (new, required), `exposure_s` (new, default 2.0), `settle_time_s` (new, default 2.0). No existing caller depends on the old stub signature. |
| CLI interface | **No** | `astrolabe polar` now requires `--latitude-deg` in addition to `--ra-rotation-deg`. Since the previous implementation always raised `NotImplementedFeature`, no existing workflow depends on the old argument set. |
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

**Change required:** Yes.

- Added `ServiceError` to the import from `astrolabe.errors`.
- Updated `run_polar()` to pass `site_latitude_rad`, `exposure_s`, and `settle_time_s` to `service.run()`.
- Added `except ServiceError` handler that outputs JSON envelope or stderr message and returns exit code 1.

```python
from astrolabe.errors import NotImplementedFeature, ServiceError

# ... in run_polar():
result = service.run(
    ra_rotation_rad=math.radians(args.ra_rotation_deg),
    site_latitude_rad=math.radians(args.latitude_deg),
    exposure_s=args.exposure,
    settle_time_s=args.settle_time,
)
```

### 7.3 `astrolabe/cli/main.py`

**Change required:** Yes.

Added three arguments to the `polar` subcommand parser:

```python
polar_parser.add_argument(
    "--latitude-deg", type=float, required=True,
    help="Observer latitude in degrees (positive north)",
)
polar_parser.add_argument(
    "--exposure", type=float, default=2.0,
    help="Exposure time in seconds (default: 2.0)",
)
polar_parser.add_argument(
    "--settle-time", type=float, default=2.0,
    help="Settle time after slew in seconds (default: 2.0)",
)
```

---

## 8. Implementation Notes

### 8.1 Circle fitting history

The original plan specified a single least-squares path via normal equations (`AᵀA x = Aᵀb`) applied to perpendicular bisecting planes for all N≥3. During implementation this was observed to be rank-deficient for N=3 (only 2 distinct bisecting planes ⇒ 2 equations in 3 unknowns). A cross-product specialisation for N=3 was added, with least-squares reserved for N>3.

Post-review (PR #29) the whole scheme was replaced. The bisecting-plane-with-midpoint formulation turns out to be degenerate for *any* N when all observations lie on the unit sphere: every bisecting plane passes through the origin (`nᵢ · midᵢ = (|P_j|² − |P_i|²)/2 = 0`), so the normal-equations RHS vector is identically zero and the minimum-norm solution is `x = 0`. The previous N>3 path was saved only by floating-point noise producing a non-zero direction.

The current implementation reformulates the fit directly in terms of the pole equation `p · vᵢ = cos r` with unknowns `(p, c)`, fixes the dominant component of `p` via the observation centroid, and solves the resulting 3-unknown overdetermined system by least-squares. It works uniformly for all N≥4 (the structural minimum for a meaningful residual), is order-invariant, and has no special-case branches.

### 8.2 Great-circle detection

On a sphere, any 3 non-coincident, non-antipodal points define a unique small circle. Points on a great circle produce a valid fit with radius = π/2 (90°), but this is meaningless for polar alignment. The implementation rejects fits where the radius is within 1° of π/2, raising `ValueError("Points lie on or near a great circle")`.

### 8.3 MountState lacks `latitude_rad`

The plan originally assumed `MountState` would have a `latitude_rad` field for fallback. The actual `MountState` dataclass only has: `connected`, `ra_rad`, `dec_rad`, `tracking`, `slewing`, `timestamp_utc`. Rather than modifying `MountState` (which would affect all mount backends), `site_latitude_rad` was made a required parameter. This is consistent with the CLI approach of requiring `--latitude-deg`.

### 8.4 CameraBackend.capture() requires exposure_s

The plan originally specified `exposure_s: float | None = None` with the camera backend using its own default. The actual `CameraBackend.capture()` signature requires `exposure_s` as a positional argument. The service defaults to 2.0 seconds, a common plate-solving exposure.

---

## 9. Execution Record

### Phase 1: Package structure created

1. Created `astrolabe/services/polar/` directory.
2. Created `astrolabe/services/polar/__init__.py` with re-exports.
3. Created `astrolabe/services/polar/types.py` with `PolarResult`, `_PoseObservation`, `_CircleFitResult`.
4. Created `astrolabe/services/polar/math.py` with `fit_polar_axis()`, `_fit_circle_spherical()`, `_fit_pole_lstsq()`, `_solve_3x3_cramer()`, `_pole_to_altaz_error()`, `correction_confidence()`.
5. Created `astrolabe/services/polar/service.py` with `PolarAlignService` class.

### Phase 2: Flat file replaced

6. Deleted `astrolabe/services/polar.py`.

### Phase 3: CLI wiring updated

7. Updated `astrolabe/cli/main.py` — added `--latitude-deg`, `--exposure`, `--settle-time` arguments.
8. Updated `astrolabe/cli/commands.py` — added `ServiceError` import, updated `run_polar()` to pass new parameters, added `ServiceError` handler.

### Phase 4: Test infrastructure created

9. Created `tests/services/__init__.py` (empty).
10. Created `tests/services/polar/__init__.py` (empty).
11. Created `tests/services/polar/test_math.py` with 13 unit tests.
12. Created `tests/services/polar/test_service.py` with 12 service tests.

### Phase 5: Validation

13. `pytest tests/services/polar/` — **47 passed**.
14. `pytest` (full suite, excluding pre-existing optional-dep `ty` checks) — **248 passed, 3 skipped**, 0 failed.
15. Import verification:
    - `from astrolabe.services import PolarAlignService, PolarResult` — OK.
    - `from astrolabe.services.polar import PolarAlignService, PolarResult` — OK.

---

## 10. Summary

| Aspect | Count |
|--------|-------|
| New files | 8 |
| Deleted files | 1 |
| Modified files | 2 (`cli/main.py`, `cli/commands.py`) |
| New test files | 2 |
| Total test cases | 25 (13 math + 12 service) |
| New internal types | 2 (`_PoseObservation`, `_CircleFitResult`) |
| New public types | 0 (only `PolarResult`, already existed) |
| Breaking changes | 0 |

**Total impact:** Low-risk refactor with no public API breakage. All imports resolve correctly post-migration. The N-pose circle-fitting method (N≥4, default 4) provides a meaningful fit residual for confidence estimation, honest handling of missing per-solve RMS, and CLI error propagation on service failure. CLI exposes `--latitude-deg`, `--exposure`, `--settle-time`, and `--num-poses`.
