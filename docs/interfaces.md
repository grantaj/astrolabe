# Interfaces

This document defines the logical interfaces between Astrolabe modules.

These interfaces enforce architectural separation between:
- Hardware backends (camera, solver, mount)
- Core services (goto, polar, guiding)
- CLI layer

All conventions referenced here follow `docs/conventions.md`.

---

# 1. Core Data Types

## 1.1 Image

Represents a captured frame.

Fields (conceptual):

- data: 2D array (implementation-defined)
- width_px: int
- height_px: int
- timestamp_utc: datetime (UTC)
- exposure_s: float
- metadata: dict

Image objects are opaque to services except for guiding (which may access pixel data).

---

## 1.2 SolveResult

Returned by SolverBackend.

All angular values are in **radians** (ICRS).

Fields:

- success: bool
- ra_rad: float
- dec_rad: float
- pixel_scale_arcsec: float
- rotation_rad: float
- rms_arcsec: float
- num_stars: int
- message: optional string

If success == False, other fields may be None.

---

## 1.3 SolveRequest

Represents inputs to the solver.

Fields (conceptual):

- image: Image
- ra_hint_rad: optional float
- dec_hint_rad: optional float
- scale_hint_arcsec: optional float
- parity_hint: optional int
- search_radius_rad: optional float
- timeout_s: optional float
- extra_options: optional dict

---

## 1.4 MountState

Represents mount state in internal frame (ICRS).

Fields:

- connected: bool
- ra_rad: float
- dec_rad: float
- tracking: bool
- slewing: bool
- timestamp_utc: datetime

Mount backends must convert from mount-native frame to ICRS before returning.

---

# 2. Backend Interfaces

Backends isolate hardware or external tools.

Core logic must only depend on these interfaces.

---

## 2.1 CameraBackend

Responsibilities:
- Connect to physical camera
- Capture frames

Interface (conceptual):

connect() -> None
disconnect() -> None
is_connected() -> bool

capture(
    exposure_s: float,
    gain: optional float,
    binning: optional int,
    roi: optional tuple
) -> Image

Notes:

- `capture` returns an `Image` with `data` set to an on-disk path when the backend
  uses local file capture (e.g., INDI upload-to-local).
- Backends should populate `timestamp_utc` and `exposure_s` reliably.

No plate solving logic permitted here.

---

## 2.2 SolverBackend

Responsibilities:
- Run plate solving
- Parse results into SolveResult

Interface:

solve(request: SolveRequest) -> SolveResult

Solver must return results in ICRS (J2000-equivalent) coordinates.

Solver backends handle unit conversions required by external tools (e.g., degrees/hours),
but must expose and accept radians at the interface boundary.

Solver must not perform mount logic.

---

## 2.3 MountBackend

Responsibilities:
- Connect to mount
- Provide primitive motion commands
- Convert coordinate frames at boundary

Interface:

connect() -> None
disconnect() -> None
is_connected() -> bool

get_state() -> MountState

slew_to(ra_rad: float, dec_rad: float) -> None
sync(ra_rad: float, dec_rad: float) -> None
set_tracking(enabled: bool) -> None
stop() -> None
park() -> None

pulse_guide(ra_ms: float, dec_ms: float) -> None

Notes:

- slew_to and sync expect ICRS inputs.
- Backend performs ICRS → apparent conversion internally.
- Backend may require site latitude/longitude/elevation for frame conversion.
- set_tracking controls mount sidereal tracking: enabled=True starts tracking, enabled=False stops.
- Auto-connect: All state-reading and state-modifying operations (get_state, slew_to, sync,
  set_tracking, park, pulse_guide) connect the mount if not already connected. stop() and
  disconnect() never auto-connect.
- pulse_guide uses milliseconds duration convention.
- Positive RA pulse increases RA tracking rate temporarily.
- Positive DEC pulse increases declination.
- Slewing detection: Backend observes coordinate property state to detect active slews.
  When slew is in progress, the coordinate property state becomes "Busy".

---

# 3. Service Interfaces

Services orchestrate backends.

They contain math and policy but no hardware-specific code.

---

## 3.1 GotoService

Responsibilities:
- Closed-loop centering

Interface:

center_target(
    target_ra_rad: float,
    target_dec_rad: float,
    tolerance_arcsec: float,
    max_iterations: int
) -> GotoResult

GotoResult (conceptual):

- success: bool
- final_error_arcsec: float
- iterations: int
- message: optional string

---

## 3.2 PolarAlignService

Responsibilities:
- Perform polar alignment routine
- Compute altitude and azimuth corrections

Interface:

run(
    ra_rotation_rad: float
) -> PolarResult

PolarResult:

- alt_correction_arcsec: float
- az_correction_arcsec: float
- residual_arcsec: float
- confidence: float (0–1)
- message: optional string

All corrections are relative mechanical adjustments.

---

## 3.3 AlignmentService

Responsibilities:
- Plate-solve-based alignment and sync
- Initial multi-point alignment modeling

Interface:

sync_current(
    exposure_s: optional float
) -> AlignmentResult

solve_current(
    exposure_s: optional float
) -> SolveResult

initial_alignment(
    target_count: int,
    exposure_s: optional float,
    max_attempts: optional int
) -> AlignmentResult

AlignmentResult (conceptual):

- success: bool
- solves_attempted: int
- solves_succeeded: int
- rms_arcsec: optional float
- message: optional string

---

## 3.4 GuidingService

Responsibilities:
- Star detection
- Calibration
- Closed-loop guiding

Interface:

calibrate(duration_s: float) -> CalibrationResult

start(
    aggression: float,
    min_move_arcsec: float
) -> None

stop() -> None

status() -> GuidingStatus

GuidingStatus:

- running: bool
- rms_arcsec: float
- star_lost: bool
- last_error_arcsec: float

Guiding loop must use radians internally and report arcseconds externally.

---

# 4. Planner

Responsibilities:
- Provide a curated, feasible, actionable list of targets for a time window + location
- Apply feasibility constraints (sun, altitude, moon separation)
- Provide sectioned output (showpieces, seasonal highlights, solar system, bonus/challenge)

Interface:

plan(
    window_start_utc: optional datetime,
    window_end_utc: optional datetime,
    location: optional ObserverLocation,
    constraints: optional PlannerConstraints
) -> PlannerResult

Planner defaults:
- window: now → +3h
- sun_altitude_max_deg: -12
- min_altitude_deg: 30
- min_duration_min: 30
- moon_separation_min_deg: 35
- moon_separation_strict_deg: 45 (when moon illumination > 50%)

PlannerResult (conceptual):

- window_start_utc: datetime
- window_end_utc: datetime
- location: ObserverLocation
- sections: list of PlannerSection
- message: optional string

PlannerEntry (conceptual):

- id: str
- name: str
- target_type: str
- best_time_utc: datetime
- peak_altitude_deg: float
- time_above_min_alt_min: float
- moon_separation_deg: float
- moon_illumination: float
- score: float (0–100)
- score_components: dict (normalized factors)
- notes: list[str]
- difficulty: str (easy / medium / hard)

---

# 5. Error Model

Backends should raise structured exceptions or return error objects.

Services decide:

- Retry vs fail
- User-facing messaging
- Exit codes via CLI

No backend should print directly to stdout.

Preferred exception hierarchy (conceptual):

- AstrolabeError
  - BackendError
  - ServiceError
  - NotImplementedFeature

---

# 6. Invariants

- All internal angles are radians.
- All internal coordinates are ICRS.
- Mount frame conversion happens only inside MountBackend.
- Services are backend-agnostic.
- CLI depends only on service interfaces.

Any change to these interfaces must be treated as a breaking architectural change.
