# Pointing Error Model & Perturbation Reference (v1)

This document captures reference math for the initial pointing error model and the test-only perturbation model used with INDI simulators. Internal units are radians (ICRS). Human-facing outputs are converted to degrees/arcmin/arcsec.

---

## 1. Coordinate Conventions

- Internal coordinates: ICRS, radians.
- Small-angle approximation is valid for error vectors within a few degrees.
- Define local tangent-plane error components at the target:
  - `d_alpha = (ra_solved - ra_target) * cos(dec_target)`
  - `d_delta = (dec_solved - dec_target)`
- Error vector in tangent plane: `e = [d_alpha, d_delta]^T`.

---

## 2. Minimal Error Model (v1)

We model systematic pointing error as a linear transform plus bias in the tangent plane:

```
 e_obs = A * e_cmd + b
```

For v1, use a simplified model where `e_cmd` is zero (we model the residual error after a commanded slew):

```
 e_obs = b
```

Where:
- `b = [b_alpha, b_delta]^T` is a constant offset (index error).

Optional extensions (still linear, still cheap):

**Scale + rotation:**

```
 A = s * R(theta)
 R(theta) = [[cos(theta), -sin(theta)],
             [sin(theta),  cos(theta)]]
```

**Anisotropic scale + rotation:**

```
 A = R(theta) * diag(s_alpha, s_delta)
```

**Small cone error (cross-term):**

```
 e_obs = A * e_cmd + b + c * [d_delta, d_alpha]^T
```

Where `c` is a small coupling coefficient.

---

## 3. Polar Misalignment (Optional v1.5)

Polar misalignment introduces sky-dependent errors. A simple empirical model:

```
 d_alpha += k_az * sin(HA) + k_alt * cos(HA)
 d_delta += k_az * cos(HA) * sin(lat) - k_alt * sin(HA) * sin(lat)
```

Where:
- `HA` is hour angle of target
- `lat` is site latitude
- `k_az`, `k_alt` are small coefficients (radians)

This is only for test perturbations or later model terms.

---

## 4. Perturbation Model for Simulation Tests

This model is applied only in tests/simulation to create "bad setup" conditions. It perturbs the mount-reported or solved coordinates.

Given a target `(ra, dec)`:

1. Compute tangent-plane error vector `e = [0, 0]^T` (we start with no error).
2. Apply deterministic perturbations:

```
 e = b
 e = A * e
 e = e + c * [e_delta, e_alpha]^T
```

3. Convert back to sky coordinates:

```
 ra_perturbed  = ra + e_alpha / cos(dec)
 dec_perturbed = dec + e_delta
```

Recommended parameter ranges (radians):
- `b_alpha`, `b_delta`: up to ~0.01 rad (about 34 arcmin)
- `theta`: up to ~0.02 rad (about 1.1 deg)
- `s_alpha`, `s_delta`: 1.0 +/- 0.01
- `c`: up to ~0.01

### Test-only injection strategy (preferred)

Wrap the mount backend in tests and perturb the **commanded slew target** before passing it through. This keeps production code clean and yields realistic off-target behavior when combined with real solver outputs from the CCD simulator.

---

## 5. Model Update (Learning)

The pointing model should only update after successful centering:

- Compute residual error `e_residual` at convergence.
- Update offset term with a bounded step:

```
 b_new = (1 - w) * b_old + w * e_residual
```

Where `w` is a small learning rate (e.g., 0.1) gated by solve quality.

If using rotation/scale terms in v1.5+, update via least-squares on a small set of observations spanning the sky.

---

## 6. Diagnostic Signals (Derived)

These diagnostics are based on error patterns:

- **Large constant offset**: likely time/location/hemisphere error or missing sync.
- **Sky-dependent rotation**: suggests polar misalignment or non-orthogonality.
- **Non-convergent corrections**: likely backlash/clutch slip.

---

## 7. Notes

- v1 should start with **offset-only**; this is robust and easy to validate.
- Scale/rotation terms can be added once persistence and diagnostics are stable.
- All math here is reference-level; implementations should use clear helper functions and unit tests.
