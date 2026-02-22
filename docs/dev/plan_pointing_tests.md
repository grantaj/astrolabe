# Pointing Service Test Plan (TDD)

This plan defines the test-first strategy for the Pointing service, using the INDI telescope simulator and CCD simulator (GSC-enabled) as the primary integration harness. The goal is to validate solve-as-you-go pointing, model learning, persistence, and diagnostics with real solver + real simulated images.

---

## 1. Scope and Principles

- **Use real solver and real simulated images** (INDI CCD simulator with GSC).
- **Prefer integration tests** where feasible; only use unit tests for deterministic policy/logic.
- **Gate model learning**: do not persist or update models on low-confidence solves.
- **Maintain invariants**: internal radians, ICRS, no backend logic in services.

---

## 2. Test Harness Requirements

### 2.1 External dependencies
- INDI server
- INDI telescope simulator
- INDI CCD simulator with GSC enabled
- Real solver backend configured for Astrolabe

### 2.2 Local config prerequisites
- Config points camera backend to CCD simulator
- Config points mount backend to telescope simulator
- Solver backend configured to use available solver
- Site location configured (required for mount boundary conversion)

### 2.3 Test data and artifacts
- `pointing.json` persisted state file
- Optional save directory for captured frames (for debugging)

---

## 3. Test Categories

### 3.1 Pure unit tests (fast, deterministic)
These do not depend on INDI.

- **Centering policy**
  - clamp step size (`max_step_deg`, `min_step_arcsec`)
  - enforce `max_iters`, `max_total_time_s`
  - exit reasons: success, max iters, timeout, non-convergent, stagnant

- **Quality gate logic**
  - accepts high-quality solve
  - rejects low-star / high-rms / low-confidence

- **Persistence helpers**
  - load missing file -> empty model
  - save writes atomic file
  - reset clears state

Note: unit tests should be small and focus on policy math, not solver behavior.

### 3.2 Service-level tests with INDI (primary)
Use real camera capture and real solver output from simulated star fields.

**A. `pointing where`**
- `where` returns SolveResult with non-null RA/Dec.
- Reported RA/Dec is consistent across repeated captures (within tolerance).

**B. `pointing goto` (center_target)**
- Slew to target, converge within tolerance.
- Verify error decreases each iteration until success.
- Verify iteration count is bounded.

**C. `pointing calibrate`**
- Executes multi-target calibration.
- Produces successful solves count >= target_count.
- Updates session model only on success.

**D. Persistence**
- After a successful `goto` or `calibrate`, `pointing.json` is created/updated.
- On a new process invocation, `pointing.json` is loaded and improves convergence speed or requires fewer iterations.

**E. `pointing recover`**
- Simulate failure (e.g., overexposure or zero exposure) and ensure:
  - recovery attempts are made
  - learning is disabled
  - diagnostic output includes actionable detector results

**F. Diagnostics**
- `pointing status` returns confidence, model_state, and warnings.
- `pointing diagnose` returns structured findings with severity + suggestions.

---

## 4. Concrete Test Cases (Initial)

### 4.1 Integration: `pointing where`
1. Start INDI server with mount + CCD simulators.
2. Call `pointing where`.
3. Assert:
   - success == true
   - ra_rad/dec_rad not null
   - num_stars > 0

### 4.2 Integration: `pointing goto` converges
1. Choose a bright target (fixed RA/Dec).
2. Call `pointing goto` with tolerance = 60 arcsec.
3. Assert:
   - success == true
   - final_error_arcsec <= tolerance
   - iterations <= max_iters

### 4.3 Integration: persistence across invocations
1. Run `pointing goto` to generate `pointing.json`.
2. Start a new process and run `pointing goto` to the same or nearby target.
3. Assert:
   - state file loaded
   - convergence in <= previous iteration count (or comparable)

### 4.4 Integration: calibrate path
1. Call `pointing calibrate --targets N`.
2. Assert:
   - success == true
   - solves_succeeded >= N
   - `pointing.json` updated

### 4.5 Integration: recovery path
1. Intentionally make image unsolveable (e.g., exposure too short or too long).
2. Call `pointing recover`.
3. Assert:
   - success == false or partial
   - diagnostics include "Unsolveable image" or similar
   - model not updated

---

## 5. Quality Gates (v1 defaults)

These are initial thresholds; tune after observing simulator output.

- `SolveResult.success` must be true
- `num_stars >= 20`
- `rms_arcsec <= 30`
- If expected plate scale is known: `pixel_scale_arcsec` within ±20%

---

## 6. Diagnostic Detectors (v1)

Start with the most actionable, low-ambiguity detectors:

1. Unsolveable image (repeat fails, `num_stars == 0`)
2. Low stars / high RMS (soft focus, clouds)
3. Plate scale mismatch (wrong focal length/binning/ROI)
4. Non-convergent corrections (backlash/clutch slip)
5. Large first-miss (time/location/hemisphere wrong)

---

## 7. Tooling and Execution

- Primary harness: `pytest` with a fixture to ensure INDI services are running.
- Mark INDI tests as `@pytest.mark.indi` and allow explicit opt-in.
- Skip INDI tests when simulator binaries are missing.

---

## 8. Success Criteria

- End-to-end centering works with real solver + INDI simulators.
- Pointing model persists across invocations and does not regress.
- Diagnostics provide useful operator guidance.
- All tests pass reliably on repeated runs.

---

## 9. Open Decisions

- Exact location of `pointing.json` on disk (config vs state directory).
- Thresholds for solver quality gates and detector heuristics.
- Tolerance defaults per system type (widefield vs narrowfield).
- Test-only perturbation shim design (wrap mount backend, perturb commanded targets).
