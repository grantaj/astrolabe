# Astrolabe Planner — Camera-Derived Seeing & Transparency (plan_planner_seeing.md)

**Project:** Astrolabe  
**Component:** Planner (Operational Layer)  
**Purpose:** Define approach for estimating observing conditions (seeing, transparency, cloud) using the camera instead of external weather services.

This document complements:
- `astrolabe_planner_v1_planning.md`
- `astrolabe_planner_providers_v1.md`

---

## Implementation Audit

**Status:** Future work / not implemented on `origin/main`.

Implemented:
- No camera-derived seeing, transparency, cloud, FWHM, HFD, or star-count condition estimator exists.
- No `ConditionsProvider` or `CameraConditionsProvider` interface exists.

Still relevant:
- The offline-first motivation still aligns with the planner implementation.
- Camera-derived conditions remain a plausible future direction, especially because planner operation should not depend on weather APIs.

Stale or needs revision before implementation:
- The document assumes reusable star-detection/autofocus metrics that are not yet present as shared planner/provider APIs.
- It should be reframed as post-v1 work and tied to concrete camera/solver data products once those APIs stabilize.

Still todo:
- Define condition metrics that can be computed from existing capture/solve outputs.
- Add a provider interface and a null fallback.
- Add sample FITS-based tests before wiring condition scores into planner ranking.

---

# 1. Motivation

Astrolabe is offline-first.

Weather APIs introduce:
- Network fragility
- API drift
- External dependencies
- Limited reliability at the observing site

For **operational planning (at the scope)**, local camera-derived measurements are often more accurate than forecasts.

Therefore, Astrolabe can avoid weather integration entirely for v1 and instead derive conditions directly from the imaging system.

---

# 2. Scope of Camera-Based Conditions

Camera-based estimation is appropriate for:

- Operational decision-making (what to observe now)
- Mode selection (planetary vs DSO vs bright clusters)
- Ranking adjustments

Camera-based estimation is NOT appropriate for:

- Strategic trip planning (days in advance)
- Pre-departure decisions
- Wind forecasting
- Dew risk prediction

---

# 3. Conditions We Can Estimate

## 3.1 Seeing (Atmospheric Steadiness)

Estimate via short-exposure star analysis.

Metrics:

- Median FWHM (Full Width Half Maximum)
- HFD (Half Flux Diameter)
- Centroid RMS motion across frames (jitter)
- Frame-to-frame PSF variation

Interpretation:

- Smaller FWHM → better seeing
- Larger centroid RMS → poor seeing or wind

Output bucket:

- good
- mixed
- bad

---

## 3.2 Transparency (Haze / Thin Cloud)

Estimate via:

- Star count above threshold
- Relative flux stability
- Background sky level
- Comparison to expected magnitude distribution (future enhancement)

Heuristics:

- Significant star count drop → poor transparency
- Elevated sky background → haze/moon/cloud
- Spatial gradient → patchy cloud

Output bucket:

- good
- mixed
- poor

---

## 3.3 Coarse Cloud Detection

Indirect inference only:

- Sudden star count collapse
- Plate solving failure rate increase
- Spatial brightness gradients
- Background variance increase

Cloud detection is binary/coarse only.

---

# 4. Minimal Implementation Strategy (v1.5 Target)

Reuse star detection logic from:

- Plate solving pipeline
- Autofocus metrics

Algorithm:

1. Capture N short exposures (e.g. 10 frames).
2. Detect stars (threshold + centroid).
3. Compute:
   - median FWHM
   - star count
   - centroid RMS across frames
   - background median
4. Map metrics to condition buckets via fixed thresholds.

No ML.
No calibration required initially.

---

# 5. Provider Architecture

Introduce:

```python
class CameraConditionsProvider(ConditionsProvider):
    def conditions(self, window, site) -> ConditionsProfile:
        ...
```

Returns:

```python
ConditionsProfile(
    seeing="good|mixed|bad",
    transparency="good|mixed|poor",
    cloud="clear|patchy|overcast"
)
```

Planner core remains unchanged.

If camera not connected:

- Fallback to `NullConditionsProvider`.

---

# 6. Integration with Planner

Conditions influence:

- Mode weighting (e.g. planetary favored if seeing good)
- Moon penalty scaling (poor transparency increases penalty)
- Small-object weighting (poor seeing penalizes tiny galaxies)
- High-magnification suitability

Planner must remain deterministic given same measured metrics.

---

# 7. Calibration Strategy (Future)

Possible enhancements:

- Baseline star count for site + camera stored in cache
- Compare current count vs historical best-of-night
- Track trends over session
- Long-term statistics per site

Not required for initial implementation.

---

# 8. Benefits

- Fully offline
- More accurate at the scope than forecast
- No API dependency
- Integrates naturally with imaging pipeline
- Reuses plate-solve star detection infrastructure

---

# 9. Limitations

- Cannot predict future conditions
- Cannot assist pre-trip decision
- Requires camera to be running
- Requires focus reasonably close to optimal

---

# 10. Decision Summary

1. Weather APIs are not required for v1.
2. Camera-derived conditions are preferred for operational planning.
3. Implement as optional `CameraConditionsProvider`.
4. Fallback remains `NullConditionsProvider`.
5. Strategic/tactical weather integration deferred.

---

# 11. Implementation Checklist

- [ ] Define `CameraConditionsProvider` interface
- [ ] Implement star detection metrics extraction
- [ ] Compute FWHM + star count + centroid RMS
- [ ] Define fixed bucket thresholds
- [ ] Integrate into planner scoring adjustment
- [ ] Add fallback logic
- [ ] Add regression tests using sample FITS frames

---

*End of document.*
