# Astrolabe Pointing: Solve‑as‑you‑go Pointing & Diagnostics (Design Doc)

**Goal:** Improve GoTo performance such that **success = target centered**.  
**Philosophy:** Alignment is not a mandatory user ritual. Astrolabe continuously refines an internal pointing model from routine plate solves. Explicit alignment is only needed for recovery/diagnostics or user preference.

---

## 1. User Experience

### 1.1 Happy path
1. User powers on mount.
2. `astrolabe mount where`
   - capture → solve → report current pointing (and optionally reconcile mount state if supported).
3. `astrolabe goto <target>`
   - slew → solve → refine until centered (bounded loop).
   - update session pointing model when confidence is high.

### 1.2 Optional commands
- `astrolabe pointing calibrate` (optional): guided calibration before observations.
- `astrolabe pointing recover`: recovery workflow when pointing fails.
- `astrolabe pointing status`: shows pointing confidence + active warnings.
- `astrolabe pointing diagnose`: runs detectors and prints evidence + suggested actions.

---

## 2. Core Concepts

### 2.1 Solved Pose
A successful plate solve produces:

```text
SolvedPose:
  ra_deg, dec_deg
  roll_deg            # field rotation / orientation
  scale_arcsec_per_px  # empirical plate scale
  timestamp
  quality: SolveQuality
```

`SolveQuality` should include (as available): matched stars count, residual/error metric, confidence score, etc. When unavailable, derive heuristics (see §6).

### 2.2 Two-layer pointing model
- **Session model (volatile):** updates freely (with gates) during a session.
- **Persistent model (conservative):** updated only after repeated high-confidence evidence and stored on disk (`pointing.json`).

Rationale: prevents “learning garbage” during clouds, bad focus, etc.

### 2.3 Observation log
Store small rolling history:

```text
PointingObservation:
  target_ra_dec
  solved_before_ra_dec
  solved_after_ra_dec
  alt_az (if computable)
  timestamp
  residual_arcmin
  solve_quality_snapshot
  notes / flags
```

---

## 3. Centering Loop (Goto always centers when solvable)

### 3.1 High-level algorithm
1. Command mount slew to requested target.
2. Capture image → plate solve → compute pointing error vector.
3. If within tolerance: done.
4. Else compute corrective move and repeat (bounded).

### 3.2 Safety bounds (must have)
- `MAX_ITERS` (suggest 6–8)
- `MAX_TOTAL_TIME` (suggest 180s)
- `MAX_STEP_DEG` (suggest 2°) to prevent huge corrective leaps
- `MIN_STEP_ARCSEC` (suggest 30–60″ equiv) to avoid dithering
- `MIN_IMPROVEMENT_RATIO` (e.g. 20% improvement every 2 iterations)

### 3.3 Convergence rules (stop conditions)
Stop with **SUCCESS** when:
- error <= `CENTER_TOL_ARCMIN` (configurable), or
- optional pixel-space tolerance if plate scale known.

Stop with **FAILURE** when:
- consecutive solve failures > `N_FAIL_SOLVES`
- error increases twice consecutively
- error stagnates (no significant improvement) for `K` iterations
- mount command errors / non-response detected
- exceeded `MAX_ITERS` or `MAX_TOTAL_TIME`

### 3.4 Step strategy (robustness)
- First 1–2 iterations: allow larger correction (capped).
- Later iterations: damp correction (e.g., apply 60–80% of computed correction) to reduce overshoot/backlash effects.
- Optional: “final approach from same direction” policy to mitigate backlash (configurable).

---

## 4. Continuous Improvement (Model Learning)

### 4.1 When to update session model
Update only if:
- solve quality is high AND consistent
- centering loop converged to SUCCESS
- mount response looked sane (monotonic improvement or within tolerance)
- not in “recovery mode”

### 4.2 Persistent model update gate
Promote updates only if:
- >= 3 successful, high-quality observations
- spanning different sky regions (e.g., separated by > 30°)
- and model residual improves or remains stable

### 4.3 Model complexity roadmap
- **v1:** global offset / local sync-like correction
- **v2:** local linear model (2D) per region
- **later:** full pointing model terms (cone error, non-orthogonality, flexure, refraction)

---

## 5. `pointing where` (Anchor primitive)

`pointing where` should:
- capture → solve
- report RA/Dec and optionally Alt/Az
- report confidence indicator (green/amber/red)
- optionally reconcile mount state if mount supports “sync/set current coords” (behind flag for v1)

---

## 6. Diagnostics & Common Error State Detectors

Each detector returns:
- `severity` (INFO/WARN/ERROR)
- `label` (short human-readable)
- `evidence` (metrics + counts)
- `suggested_actions` (user steps)
- `blocks_learning` (bool)
- `blocks_centering` (bool)

### 6.1 Unsolveable image
**Signals:** repeated solve fail, star count near zero, histogram saturated/dark.  
**Actions:** adjust exposure/gain, bin/downsample, check cap/clouds.

### 6.2 Bad focus / soft image / dew
**Signals:** poor focus metric (HFR/FWHM proxy), low star contrast.  
**Actions:** refocus, check dew heater, inspect optics.

### 6.3 Trailing / tracking off / vibration
**Signals:** star elongation metric above threshold; worsens with exposure.  
**Actions:** shorten exposure, check tracking on, balance, wind.

### 6.4 Plate scale/FOV inconsistent (wrong config)
**Signals:** empirical plate scale differs from expected by > X% or varies frame-to-frame.  
**Actions:** verify focal length, reducers/barlows, pixel size, binning, ROI.

### 6.5 Mount time/location/hemisphere/mode likely wrong
**Signals:** huge systematic first-miss (tens of degrees), solve-vs-mount coordinate disagreement (if readable).  
**Actions:** verify date/time/timezone, lat/long, hemisphere, EQ/AltAz mode.

### 6.6 Mount non-response / backlash / stiction / clutch slip
**Signals:** commanded corrections don’t move solved position; overshoot/bounce.  
**Actions:** approach-from-one-direction, smaller steps, check clutches/balance/backlash.

### 6.7 Polar misalignment likely (tracking-quality warning)
**Signals:** measurable field rotation over minutes in EQ mode; systematic Dec drift patterns.  
**Actions:** run polar assist; clarify that goto can still center but long exposures/guiding will suffer.

---

## 7. Recovery Mode
When centering fails, Astrolabe should attempt escalation:

1. **Auto-tune imaging:** exposure/gain/binning
2. **Widen solve constraints:** larger search radius; relax star detection thresholds
3. **Move to “rich star field” probe:** small slew to a denser region for a diagnostic solve (optional)
4. **Stop & advise user** with a specific labeled detector result

Recovery mode should **disable model updates** and **avoid repeated large slews**.

---

## 8. Configuration Surface (initial)
- `center_tol_arcmin`
- `max_iters`, `max_total_time_s`
- `max_step_deg`, `min_step_arcsec`
- `solve_retry_count`, `solve_timeout_s`
- `learning_enabled` (on by default)
- `persistent_model_enabled` (off by default in v1)
- `final_approach_policy` (off/default)

---

## 9. Logging & Telemetry (developer-grade, user-friendly)
- Always log: solve outcomes, quality metrics, commanded moves, residuals.
- For user output, show concise:
  - `Centered in 3 iterations (residual 0.8′). Model updated (session).`
  - On failure: `Non-convergent: error increased twice. Likely backlash/slip. See diagnose output.`

---

## 10. Open Implementation Decisions (OK to defer)
- Exact solver quality metrics available from chosen solver(s)
- Whether to perform optional mount sync/set-coords in v1
- How to command “small offsets” (goto RA/Dec vs pulse guiding vs axis moves)
- How to define the persistent pointing.json schema + on-disk location.
- Whether to add a dedicated Target Resolver service for object lookup (recommended).

## 11. Seapration of Concerns
Pointing owns the error model and centering loop. We treat both Indi eqmod and the mount itself as "dumb".
Target resolution (object name → RA/Dec) is a separate service used by `goto`.
---

## Appendix A: Suggested exit reasons (enumeration)
- `CENTER_SUCCESS`
- `CENTER_FAIL_SOLVE`
- `CENTER_FAIL_NONCONVERGENT`
- `CENTER_FAIL_STAGNANT`
- `CENTER_FAIL_MOUNT_ERROR`
- `CENTER_FAIL_TIMEOUT`
- `CENTER_FAIL_MAX_ITERS`
