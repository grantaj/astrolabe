# Logical interfaces

This document describes the current logical boundaries that other Astrolabe capabilities may depend on. It is intentionally narrower than a roadmap: future APIs belong in GitHub issues, not here.

All coordinate/unit rules come from `conventions.md`.

## Shared data at capability boundaries

### Image

Current `main` represents a captured frame with an `Image` value containing a backend-defined payload, dimensions, UTC timestamp, exposure, and metadata.

The type is currently defined in `astrolabe.solver.types` even though camera produces it and solver/focus consume it. That ownership is a known architectural smell tracked by GitHub issue #57. Do not treat the current module location as a desired long-term dependency direction.

Camera live frames may carry `FitsImageData` as the payload; ordinary INDI one-shot capture may carry an on-disk FITS path. Consumers must use the camera/imaging boundary rather than import INDI details.

### SolveRequest / SolveResult

Solver-owned request/result values are the stable solver boundary.

`SolveRequest` carries an image plus optional position/scale/parity/search/timeout hints. `SolveResult` carries success, solved ICRS RA/Dec, scale, rotation, RMS, matched-star count, and optional diagnostic output.

All celestial coordinates at this boundary are radians in Astrolabe's canonical frame.

### MountState

`MountState` reports connection, optional RA/Dec, tracking, slewing, and UTC timestamp. Coordinates returned by a mount backend are converted to Astrolabe's canonical frame before leaving the backend.

## Backend contracts

### CameraBackend

Current public operations:

```text
connect()
disconnect()
is_connected()
capture(exposure_s, gain=None, binning=None, roi=None) -> Image
live_frames(..., frame_count=None) -> LiveFrameSession   # optional capability
```

`LiveFrameSession` is synchronous, single-consumer, closeable, and provides backpressure. A backend that does not support it may reject the optional capability. See `live_camera.md`.

Camera code owns camera/device semantics. It does not perform plate solving, pointing, polar alignment, or focus policy.

### SolverBackend

```text
solve(SolveRequest) -> SolveResult
is_available() -> diagnostic mapping
```

A solver backend translates external units/formats into the common solver result. It does not control the mount or implement pointing policy.

### MountBackend

Current public operations:

```text
connect()
disconnect()
is_connected()
get_state() -> MountState
slew_to(ra_rad, dec_rad)
sync(ra_rad, dec_rad)
stop()
park()
set_tracking(enabled)
pulse_guide(ra_ms, dec_ms)
```

`slew_to` and `sync` accept canonical ICRS/radian coordinates. Mount-native epoch/unit/property conversion stays inside the mount capability.

## Current service surfaces

Services orchestrate capability contracts and own domain policy/math, not hardware APIs or terminal presentation.

### PointingService

Current `main` exposes operations equivalent to:

```text
solve_current(exposure_s=None, use_mount_hints=True) -> SolveResult
sync_current(exposure_s=None) -> PointingResult
initial_alignment(target_count, exposure_s=None, max_attempts=None) -> PointingResult
apply_model(ra_rad, dec_rad) -> (ra_rad, dec_rad)
update_model_from_target(...) -> None
```

The current implementation also has implicit pointing-model persistence behaviour. Issue #59 tracks making that side effect explicit and rationalising the pointing capability boundary. Until that work lands, document the implementation as it is rather than the proposed replacement.

### PolarAlignService

The polar service performs a multiple-pose capture/solve sequence, fits the mount rotation axis, and returns signed mechanical altitude/azimuth correction estimates with residual/confidence information. It consumes mount/camera/solver contracts and contains no INDI/ASTAP-specific code.

Its detailed geometry and pose-count constraints are implementation/test concerns; the CLI exposes the supported controls.

### Focus

The focus capability exposes backend-independent multi-star HFR analysis plus a thin one-shot camera/image service. `FocusMeasurement` explicitly distinguishes valid and invalid measurements and reports HFR/scatter/star counts.

HFR is unsigned image quality. It is not a signed focuser correction and must not be passed to manual-adjustment feedback as if direction were known. See `focus.md`.

### TargetResolver

The target resolver provides deterministic offline resolution from user/catalog names to normalized target matches/records. Callers should depend on its public service surface rather than planner catalog internals.

### Feedback

The feedback service maps signed/unknown adjustment state into generic feedback semantics. Platform-specific rendering/audio is a presentation concern outside the domain service.

### Planner

The planner accepts an observing window/location/constraints and returns ranked structured target recommendations. It is offline-first in normal operation; network acquisition belongs to explicit update commands/providers rather than the planning calculation.

## Placeholder services on current main

`GotoService.center_target(...)` and the guiding service methods are present as architectural/CLI placeholders but currently raise `NotImplementedFeature`.

Do not build new code against imagined completed behaviour from old planning documents. Their future implementation is defined by current GitHub issues.

## Error boundary

Astrolabe uses structured application errors (`AstrolabeError` and specializations such as backend/service/not-implemented failures). Backends/services do not print to stdout; the CLI owns presentation and exit-code mapping.

## Interface-change discipline

These boundaries exist to prevent implementation dependencies from spreading. Change them when a concrete capability requires it, not to satisfy abstract uniformity.

If current code and this document disagree, current code/tests define implemented behaviour and the mismatch should be corrected here. Planned replacement interfaces must remain in GitHub issues until implemented.
