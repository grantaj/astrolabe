# Architecture

This document defines Astrolabe’s high-level architecture, module boundaries, and layering rules.

Goal: keep the system **instrument-like** — small, reliable, and testable — with clean separation between
core logic and hardware backends.

---

## 1. High-level design

Astrolabe is a CLI application composed of:

- **Backends** (hardware / external tooling adapters)
- **Services** (pure orchestration + math; backend-agnostic)
- **CLI** (argument parsing + output formatting)

The system is designed so that core logic can be tested with simulated backends.

---

## 2. Repository layout (intended)

```
astrolabe/
  camera/        # camera backends + capture helpers
  solver/        # plate solving backends + solve parsing
  mount/         # mount backends + mount boundary conversions
  services/
    goto/        # closed-loop centering
    alignment/   # solve-based sync + multi-point alignment
    polar/       # polar alignment routine + guidance
    guide/       # guiding loop + calibration + controller
  planner/       # target planning (catalogs + filters + scoring)
  cli/           # command handlers, formatting, exit codes
  config/        # config parsing + validation
  util/          # shared math/utilities (no backend deps)
docs/
  conventions.md
  architecture.md
```

---

## 3. Layering rules (hard constraints)

These rules prevent accidental coupling.

### 3.1 No backend imports in core logic
- `services/*` and `util/*` must not import INDI or any hardware-specific libraries directly.
- All hardware interactions occur via backend interfaces defined in `docs/interfaces.md`.

### 3.2 Time-dependent coordinate conversion belongs at the mount boundary
- Internal frame is **ICRS/J2000** (see `docs/conventions.md`).
- Conversion ICRS → apparent (JNow) happens only inside `mount/*` backends.

### 3.3 CLI is thin
- `cli/*` only:
  - parses args
  - calls services
  - formats output (human + `--json`)
  - maps errors to exit codes

### 3.4 Services are composable and deterministic
- Services should be deterministic given:
  - backend responses
  - config values
  - explicit timestamps (if required at boundaries)

---

## 4. Core modules

### 4.1 Camera module (`camera/`)
Responsibilities:
- Connect to camera backend (initially via INDI).
- Capture frames with basic controls:
  - exposure, gain, binning, ROI
- Save frames (optional) and return image objects for downstream use.

Non-responsibilities:
- No plate solving logic.
- No mount logic.

### 4.2 Solver module (`solver/`)
Responsibilities:
- Run plate solving backend (ASTAP, astrometry.net, etc.).
- Parse results and return a **SolveResult** in internal conventions.

Non-responsibilities:
- No mount control.
- No goto logic.

### 4.3 Mount module (`mount/`)
Responsibilities:
- Connect to mount backend (initially via INDI/EQMod).
- Provide mount primitives:
  - get_state, slew_to, stop, sync
  - pulse guiding (RA/DEC)
- Perform coordinate conversion at boundary:
  - Internal ICRS ↔ mount expected frame

Non-responsibilities:
- No closed-loop goto policy.
- No polar alignment algorithm.
- No guiding controller logic.

### 4.4 Services (`services/`)
Services orchestrate backends to implement features.

#### `services/goto/`
- Closed-loop centering using:
  - mount slew
  - capture
  - solve
  - compute error
  - correction slew
- Tolerance and max-iterations policy.

#### `services/polar/`
- Polar alignment routine using:
  - capture + solve at pose A
  - rotate RA axis by Δ
  - capture + solve at pose B
  - compute mount axis misalignment
  - output alt/az correction guidance + confidence

#### `services/guide/`
- Guiding:
  - star detection / centroiding
  - calibration (pixel → arcsec mapping, RA/DEC response)
  - controller (P/PI)
  - pulse guide outputs
  - star-lost handling, bounds

---

## 5. Data flows

### 5.1 Plate solving flow
```
Camera.capture → Image → Solver.solve → SolveResult(ICRS)
```

### 5.2 Closed-loop goto flow
```
Target(ICRS) → Mount.slew_to(target)
           → loop:
               Camera.capture → Solver.solve → current(ICRS)
               error = target - current
               if |error| < tolerance: done
               Mount.slew_to(corrected_target)
```

### 5.3 Polar alignment flow (conceptual)
```
Pose A:
  capture → solve → field centre A (ICRS)
Rotate RA by Δ:
Pose B:
  capture → solve → field centre B (ICRS)

Compute:
  mount RA axis projection vs true pole
Output:
  ALT correction (arcsec/arcmin + direction)
  AZ  correction (arcsec/arcmin + direction)
  confidence / residual
```

### 5.4 Guiding flow (conceptual)
```
Guide loop at ~1–2 Hz:
  capture → detect star(s) → centroid shift (pixels)
  map pixels → angular error (radians / arcsec)
  controller → pulse durations (ms)
  mount.pulse_guide(ra_ms, dec_ms)
```

---

## 6. Concurrency model (minimal)

Astrolabe is primarily synchronous for commands.

Guiding introduces a loop:
- Guiding runs as a controlled loop in-process (initially).
- Other commands should not run concurrently with guiding unless explicitly supported.
- Shared access to mount/camera must be serialized.

Initial rule: **one active session owns the mount + camera**.

---

## 7. Error handling principles

- Backends return structured errors (with reason codes).
- Services decide:
  - retryable vs fatal
  - user-actionable messaging
- CLI maps to exit codes and prints:
  - human-readable summary
  - optional JSON with error details

---

## 8. Testability strategy (architectural)

- Provide fake backends for camera/solver/mount:
  - deterministic images / deterministic solve results
  - simulated mount state and response
- Unit tests focus on:
  - coordinate math
  - error computation
  - controller behaviour
- Integration tests focus on:
  - backend adapters
  - parsing solver outputs

---

## 9. Architectural invariants

- Internal frame is ICRS/J2000.
- Internal units are radians.
- All mount frame conversions happen only inside mount backends.
- Services remain backend-agnostic.
- CLI remains thin and stable.

Any violation of these invariants is considered architectural regression.
