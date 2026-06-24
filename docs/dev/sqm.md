# Astrolabe Planner — Contrast-Based Visibility Scoring (Simple Design Note)

## Implementation Audit

**Status:** Largely implemented on `origin/main`.

Implemented:
- `astrolabe/planner/visibility.py` uses SQM as the primary sky-brightness input.
- Bortle classes are converted to approximate SQM values when SQM is absent.
- Effective sky brightness is adjusted by altitude/airmass.
- Extended targets use surface-brightness contrast scoring.
- Surface brightness can be estimated from magnitude and angular area when catalog surface brightness is absent.
- Point-like targets use a telescopic limiting-magnitude margin.
- Visibility is multiplied into the broader planner score in `astrolabe/planner/scoring.py`.

Stale or different from implementation:
- Moon penalties are no longer merely "optional future"; planner scoring already includes Moon separation, illumination, and altitude.
- The final planner score is not only `visibility * altitude`; it also includes duration, Moon, size, magnitude, type, and Sun-glow components.
- Structured-object handling has already been added in `visibility.py` and is also covered by `plan_planner_structured_objects.md`.

Still todo:
- Add dedicated tests for SQM/Bortle visibility scoring and point-source limiting magnitude behavior.
- Calibrate constants such as the airmass coefficient, contrast alpha, and limiting-magnitude approximation.
- Document intended ranges and caveats in user-facing planner docs once behavior stabilizes.

---

## Goal

Provide a **defensible, physically grounded ranking metric** for astronomical targets based on:

- Sky brightness (SQM, mag/arcsec²)
- Object surface brightness (mag/arcsec²)
- Target altitude (airmass penalty)
- **Point-source detectability via limiting magnitude** (for stars / compact objects)

This document intentionally avoids implementation details.  
It defines only the **core visibility logic** for Planner.

---

# 1. Why Use Contrast Instead of Bortle?

- **Bortle** is qualitative and observer-dependent.
- **SQM (mag/arcsec²)** is numeric and measurable.
- Deep sky visibility for **extended objects** depends primarily on **surface brightness contrast**, not integrated magnitude.

Therefore:

> Planner should use SQM, not Bortle, as its primary sky quality metric.

If Bortle is provided, convert it to an approximate SQM value.

---

# 2. Two Visibility Regimes

Planner should treat targets in two broad regimes:

1) **Extended targets** (galaxies, nebulae, large clusters)  
→ rank by **surface brightness contrast** and altitude.

2) **Point-like targets** (stars, tight clusters, compact planetaries, doubles)  
→ rank by **limiting magnitude margin** (how far above/below the detection limit the object is), plus altitude.

This avoids using the wrong metric for the wrong kind of object.

---

# 3. Extended Targets: Surface Brightness Contrast

For extended objects, visibility depends on the difference between:

- Object mean surface brightness: μ_obj (mag/arcsec²)
- Effective sky brightness: μ_sky_eff (mag/arcsec²)

Define:

Δμ = μ_obj − μ_sky_eff

Interpretation:

- Δμ < 0 → Object brighter than sky per arcsec² → Easy
- 0–1 → Good contrast
- 1–2 → Challenging
- > 2 → Very difficult

Smaller Δμ is better.

---

# 4. Sky Brightness Model

## 4.1 Zenith Sky Brightness

Use:

μ_sky_zenith = SQM

Typical values:

- 21.7 → very dark rural
- 21.0 → rural/suburban
- 20.0 → suburban
- 19.0 → bright suburban

Higher number = darker sky.

---

## 4.2 Altitude / Airmass Penalty

Sky becomes brighter toward the horizon.

Let X = airmass.

Effective sky brightness:

μ_sky_eff = μ_sky_zenith − c × (X − 1)

Where:

- X ≈ 1 / sin(altitude)
- c ≈ 0.8 (reasonable constant for v1)

Lower altitude → higher X → brighter sky → worse contrast.

Objects below a minimum altitude (e.g., 25°) should be rejected.

---

# 5. Object Surface Brightness

If catalog provides μ_obj, use it.

If not, estimate from integrated magnitude and apparent area.

For an object with:

- magnitude m
- major axis a (arcmin)
- minor axis b (arcmin)

Convert to arcsec:

a_sec = a × 60  
b_sec = b × 60  

Area (ellipse):

A = π × (a_sec / 2) × (b_sec / 2)

Then:

μ_obj ≈ m + 2.5 log10(A)

This gives mean surface brightness in mag/arcsec².

---

# 6. Extended-Target Contrast Score

Define:

Δμ = μ_obj − μ_sky_eff

Map this to a smooth visibility score.

Proposed simple mapping:

contrast_score = exp(−α × max(0, Δμ))

Where:

- α ≈ 1.0–1.5
- If Δμ < 0, score = 1

Properties:

- Monotonic
- Physically motivated
- No arbitrary hard thresholds
- Easy to explain

---

# 7. Point Sources: Limiting Magnitude

For point-like objects, surface brightness is not the right tool. Use **limiting magnitude**.

## 7.1 Naked-eye limiting magnitude (NELM) from SQM

A simple approximation used in practice:

NELM ≈ SQM − 14

Example:
- SQM 21.5 → NELM ~ 7.5
- SQM 20.0 → NELM ~ 6.0

This is an approximation (observer-dependent), but it’s a reasonable, explainable bridge from SQM to “how deep can you see”.

## 7.2 Telescopic limiting magnitude (visual, rough)

A classic rule-of-thumb for telescope limiting magnitude:

LM_tel ≈ NELM + 5 log10(D_mm) − 5

Where:
- D_mm is the telescope aperture in mm.

Example (8-inch ≈ 203 mm):
- 5 log10(203) − 5 ≈ 6.5
- So LM_tel ≈ NELM + 6.5

If SQM=21.5 → NELM ~ 7.5 → LM_tel ~ 14.0

**Important:** This is a *rough, optimistic* visual estimate. Real detectability varies with:
- magnification / exit pupil
- seeing / transparency
- observer experience
- target field crowding
- optical throughput

For Planner v1, the purpose is ranking, not promising absolute detectability.

## 7.3 Point-source score (margin to limit)

Define the “margin”:

margin = LM_tel − m_target

- Positive margin: should be visible/detectable.
- Negative margin: likely not.

Rank point targets by increasing margin (larger is better), plus altitude.

---

# 8. Altitude Weight

Even with good contrast (or good margin), higher altitude is better.

Define:

altitude_score = normalized altitude weight

Example idea:

- 0 at minimum altitude (e.g., 25°)
- 1 at zenith (90°)
- Smooth curve preferred

Altitude should not dominate contrast/margin, but should penalize low targets.

---

# 9. Final Ranking Metric

For **extended objects**:

final_score = contrast_score × altitude_weight

For **point-like objects**:

final_score = point_margin_score × altitude_weight

Where point_margin_score is any monotonic mapping of `margin` (e.g. linear clamp or a smooth sigmoid).

Optional future penalties (not required for v1):

- Moon proximity / phase
- Object type modifiers
- Transparency factor

---

# Summary

Planner should:

1. Use SQM to define sky surface brightness.
2. Adjust sky brightness for altitude (airmass).
3. For extended targets: compute μ_obj and Δμ, then rank by contrast × altitude.
4. For point sources: estimate limiting magnitude from SQM + aperture, compute margin to target magnitude, then rank by margin × altitude.

This yields a physically grounded, defensible ordering of targets by expected visibility.
