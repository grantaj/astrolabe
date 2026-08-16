# Astrolabe Planner — Handling Nebulae and Clusters in a Contrast Model

## Implementation Audit

**Status:** Mostly implemented on `origin/main`.

Implemented:
- `astrolabe/planner/visibility.py` distinguishes point-like targets from extended targets.
- Open clusters and compact point-like targets use limiting-magnitude scoring rather than surface-brightness contrast.
- Extended objects use SQM/Bortle-derived sky brightness and estimated or catalog surface brightness.
- Nebulae use a reduced size-area coefficient when estimating surface brightness.
- Nebulae/reflection objects and globular clusters receive a structure boost via `_apply_structure_boost`.

Stale or different from implementation:
- This document proposes an emission-nebula boost of about `1.5 mag`; the implementation currently uses `1.0 mag`.
- Globular clusters are boosted by `1.0 mag`, as suggested.
- The implementation applies a reduced `beta=1.5` for nebula surface-brightness estimates, which is closest to option C in this document.

Still todo:
- Add focused unit tests for structured-object visibility behavior.
- Calibrate boost values against known examples such as M42, 47 Tuc, and Omega Centauri.
- Decide whether globular clusters should eventually use a hybrid limiting-magnitude/core-contrast model.

---

## Problem

Using **mean surface brightness (μ_mean)** works reasonably well for many galaxies,  
but it fails for:

- Bright, structured emission nebulae (e.g. M42)
- Globular clusters (e.g. 47 Tuc, Omega Centauri)
- Open clusters (dominated by stars)

The failure mode:

Mean surface brightness averages over the entire angular extent of the object.  
Large objects with bright cores and faint outer regions get penalized too heavily.

This produces physically consistent numbers — but perceptually incorrect rankings.

---

# 1. Why Mean Surface Brightness Fails

## 1.1 Emission Nebulae (e.g. M42)

Observers detect:

- Bright core regions
- High-contrast structure
- Local peaks in brightness

They do **not** detect the average brightness over the full ellipse.

Thus:

μ_mean is too faint compared to how the object is actually perceived.

---

## 1.2 Globular Clusters (e.g. 47 Tuc, Omega Cen)

Globular clusters are perceived as:

- A bright condensed core
- An unresolved glow
- Then resolved stars (aperture-dependent)

Mean surface brightness across the full diameter underestimates the visual impact of the core.

---

## 1.3 Open Clusters

Open clusters are fundamentally collections of point sources.

Surface brightness is not the correct detectability model.

They should be treated as magnitude-limited star fields, not diffuse objects.

---

# 2. Usual Practical Approaches

In most practical planners and visual heuristics, one of the following is done:

## A) Use Peak / Core Surface Brightness

If available:

- Use μ_peak instead of μ_mean
- Or model the object as multi-component (core + halo)

This aligns better with human detection.

---

## B) Apply a Structure / Core Boost

If only μ_mean is available, introduce an effective brightness:

μ_eff = μ_mean − Δ_structure

Typical practical values:

- Emission nebulae: Δ ≈ 1.5 mag
- Globular clusters: Δ ≈ 1.0 mag
- Galaxies: Δ ≈ 0 (keep original model)

This is not arbitrary — it compensates for the fact that observers detect bright substructure.

---

## C) Weaken the Size Penalty

Instead of:

μ ≈ m + 2.5 log10(A)

Use a reduced coefficient for some classes:

m + β log10(A)

Where:

β < 2.5

This reduces the over-penalisation of large but structured objects.

---

## D) Use Point-Source Limiting Magnitude (for clusters)

For open clusters and partially resolved globulars:

Rank by:

margin = LM_tel − m_target

Where LM_tel is the telescopic limiting magnitude.

This reflects how observers actually detect cluster members.

---

# 3. Recommended Minimal Fix for Planner v1

To preserve the existing contrast framework while correcting behaviour:

## Step 1 — Classify object type

- Galaxy
- Emission / reflection nebula
- Globular cluster
- Open cluster

## Step 2 — Define effective surface brightness

Default:

μ_eff = μ_mean

Overrides:

- Emission nebula → μ_eff = μ_mean − 1.5
- Globular cluster → μ_eff = μ_mean − 1.0
- Open cluster → do not use μ; use limiting magnitude model

## Step 3 — Keep existing contrast machinery

Compute:

Δμ = μ_eff − μ_sky_eff

Then apply the same contrast scoring as before.

---

# 4. Why This Is Defensible

- It acknowledges that detectability is governed by **local contrast**, not global average.
- It mirrors how experienced observers actually perceive objects.
- It keeps the model simple and explainable.
- It avoids rewriting the entire visibility framework.
- It prevents clearly bright objects (e.g. M42, 47 Tuc) from being incorrectly crushed by the model.

---

# 5. Important Note on Low Altitude

If an object (e.g. Omega Centauri) is very low (e.g. 15° altitude):

- Airmass penalties are real and severe.
- Reduced visibility in this case may be physically correct.

The fix should correct structured-object bias — not remove legitimate atmospheric penalties.

---

# Summary

Mean surface brightness alone is insufficient for:

- Structured nebulae
- Globular clusters
- Open clusters

The standard practical solution is:

- Use surface brightness contrast for galaxies.
- Apply structure/core boosts for nebulae and globulars.
- Use limiting magnitude logic for open clusters.

This keeps the model physically grounded while aligning it with real visual perception.
