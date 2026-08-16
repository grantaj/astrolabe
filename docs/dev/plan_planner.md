# Astrolabe Planner v1 — Implementation Planning Document (for coding agents)

**Project:** Astrolabe  
**Component:** Planner service (offline-first)  
**Primary goal for v1:** Operational planning — produce a ranked, explainable list of targets for a given time window and observing profile, with *no internet required*.

---

## Implementation Audit

**Status:** Partially implemented on `origin/main`.

Implemented:
- `astrolabe.planner.Planner` provides an offline operational planner.
- Core request/result models exist in `astrolabe/planner/types.py`.
- Local curated catalog loading exists via `LocalCuratedCatalogProvider`.
- Built-in Sun/Moon calculations and approximate planet targets exist.
- Scoring includes altitude, duration, Moon separation/illumination, size, magnitude, type bonus, Sun glow, and SQM/Bortle-based visibility.
- `astrolabe plan` supports text/JSON output, local or UTC time windows, location overrides, `visual`/`photo` modes, and result limits.
- `astrolabe update catalog` is implemented for OpenNGC ingestion and curated catalog output.
- A deterministic planner smoke test exists.

Stale or different from implementation:
- The implemented package layout is flat under `astrolabe/planner/`; there is no `planner.core` or `planner.cli` subpackage.
- The model names differ: `ObserverLocation` exists; `SiteProfile`, `EquipmentProfile`, and `TimeWindow` do not.
- Modes are `visual` and `photo`, not `visual`, `imaging`, and `quick`.
- `update` is no longer a stub; it downloads/parses OpenNGC and writes a curated catalog.
- `doctor` is not implemented.
- Environmental/conditions provider abstractions are not implemented.

Still todo:
- Add a first-class equipment profile beyond aperture-only planner config.
- Add conditions provider interfaces and null/camera-derived implementations.
- Add strategic/tactical planner layers if still desired.
- Add stronger ranking regression tests and monotonic scoring tests.
- Decide whether to introduce a `doctor` command for offline data/config validation.

---

## 1. Context and intent

Astrolabe’s Planner is intended to be a **context-aware, opinionated decision engine** that answers:

> “Given my location, time window, and typical amateur equipment, what should I look at tonight?”

It is explicitly **not** a general-purpose sky catalog browser.

Key differentiators:
- **Opinionated**: curated defaults; avoid user-tunable weight spaghetti.
- **Offline-first**: works reliably at the scope with no internet.
- **Explainable**: each recommendation includes short reasons.

---

## 2. Scope

### In scope (v1)
- Operational planning (during observing): ranked list of targets for a time window.
- Deterministic scoring based on offline astronomical/geometric factors:
  - altitude over window / max altitude
  - time above minimum altitude (e.g. 30°)
  - culmination/transit timing within window
  - moon separation (+ basic moon brightness penalty)
  - object “observability” proxies: magnitude, angular size, surface brightness (if available)
  - field-of-view match heuristic (given an equipment profile)
- Explainability: show key reasons per target.
- Curated local catalog (ship with repo).
- Interfaces and stubs for:
  - Strategic planning (trip viability)
  - Tactical planning (tonight quality assessment)
  - Environmental inputs provider (weather/seeing/transparency)
- CLI surface sketch/stubs for `update` and `doctor`.

### Out of scope (v1)
- Real-time weather / seeing retrieval at observe time.
- Full NGC/IC/Simbad-scale catalogs.
- Learning/adaptive personalization.
- GUI.

---

## 3. Non-functional requirements
- **Offline reliability:** `plan` must succeed without network and without optional datasets.
- **Deterministic output:** same inputs → same ranked results (subject to clock/time).
- **Fast:** typical run < 1s for ~500–2000 candidates on a Raspberry Pi class CPU.
- **Pure core logic:** planner core must not depend on mount, camera, or UI.

---

## 4. Architecture overview

### Layering
- `planner.core` — pure domain logic (no IO)
- `planner.providers` — data sources + caching (IO)
- `planner.cli` — command plumbing / formatting

### Future layers (stubs in v1)
- `planner.strategic` — trip viability evaluator (stub)
- `planner.tactical` — tonight quality evaluator (stub)

### Key principle
Planner should be separable/extractable as a standalone package (minimal dependencies).

---

## 5. Data model

### 5.1 Site profile
Represents observing location and persistent site characteristics.

```python
@dataclass(frozen=True)
class SiteProfile:
    name: str
    latitude_deg: float
    longitude_deg: float
    elevation_m: float | None = None
    bortle: int | None = None           # optional; can be set manually
    sqm: float | None = None            # optional sky brightness estimate
    horizon_mask: str | None = None     # future: path to horizon profile
```

### 5.2 Equipment profile (v1: minimal)
```python
@dataclass(frozen=True)
class EquipmentProfile:
    aperture_mm: float | None = None
    focal_length_mm: float | None = None
    sensor_width_mm: float | None = None   # for imaging use cases
    sensor_height_mm: float | None = None
    eyepiece_fov_deg: float | None = None  # for visual heuristics
```

Derived values (helper functions):
- approximate FOV (deg) if focal length + sensor known
- “preferred angular size range” heuristic from FOV
- “brightness tolerance” heuristic from aperture and bortle (very coarse)

### 5.3 Planning window
```python
@dataclass(frozen=True)
class TimeWindow:
    start: datetime  # timezone-aware
    end: datetime
```

### 5.4 Target model
Curated catalog items.

```python
@dataclass(frozen=True)
class Target:
    id: str                    # stable ID used in outputs
    name: str
    ra_deg: float
    dec_deg: float
    type: str                  # e.g., "globular", "open_cluster", "emission_nebula", "galaxy", ...
    mag: float | None = None
    size_arcmin: float | None = None
    surface_brightness: float | None = None  # if available
    tags: list[str] = field(default_factory=list)  # e.g., ["southern_showpiece", "messier"]
```

---

## 6. Providers and caching

### 6.1 CatalogProvider (v1: LocalCuratedCatalogProvider)
- Loads a bundled catalog file (CSV or JSON) from `data/catalog_curated.*`
- No online operations required.

**Recommended format:** CSV with explicit columns:
`id,name,ra_deg,dec_deg,type,mag,size_arcmin,surface_brightness,tags`

### 6.2 EphemerisProvider (v1: BuiltInEphemerisProvider)
- Provides Sun/Moon positions and illumination with a simple offline algorithm/library.
- Keep provider interface so a future JPL ephemeris file provider can be added.

### 6.3 EnvironmentalConditionsProvider (stub)
- v1 default returns “unknown” conditions and does not block.
- Future: cached forecast, manual input, etc.

```python
@dataclass(frozen=True)
class ConditionsProfile:
    cloud: str | None = None       # "good"|"mixed"|"bad"|None
    transparency: str | None = None
    seeing: str | None = None
    wind: str | None = None
```

---

## 7. Operational planning algorithm (v1)

### 7.1 Candidate generation
- Start with curated catalog targets.
- Filter obvious non-starters quickly:
  - below minimum altitude for entire window
  - never rises (dec/lat geometry)
  - optional: too close to Sun (daylight/twilight check)

### 7.2 Per-target computed features
For each target and time window:
- altitude(t) curve sampled at coarse cadence (e.g., every 5–10 minutes)
- `max_alt_deg`
- `time_above_min_alt_minutes` (min alt default 30°; configurable via CLI flag)
- `culmination_time` (approx)
- Moon:
  - moon separation at mid-window (deg)
  - moon illumination fraction (0..1) or % (approx)
  - moon altitude at mid-window (optional)
- Object suitability proxies:
  - `mag` (integrated)
  - `surface_brightness` if available else derived proxy
  - `size_arcmin` vs derived FOV range

### 7.3 Scoring (opinionated, deterministic)
Score combines multiple components with curated weights per observing mode.

Define modes (v1 default: `visual`), but keep interface for future:
- `visual`
- `imaging` (stub mode ok)
- `quick` (stub mode ok)

Example scoring sketch (weights are *placeholders*; tune later):

```
S = 0
+ w_alt * f_alt(max_alt_deg)
+ w_dur * f_dur(time_above_min_alt)
+ w_moon * f_moon(separation_deg, illum)
+ w_size * f_size(size_arcmin, preferred_range)
+ w_type * f_type(type)            # e.g., bonus for clusters in bright moon
+ w_mag  * f_mag(mag)              # gentle, not dominant
```

Normalize/clip each f_* to [0,1] to keep behavior stable.

### 7.4 Explainability requirements
For each recommended target, output:
- **Score** (0–100)
- **Best time**: culmination time or “best between X–Y”
- **Altitude**: max altitude and time above threshold
- **Moon**: separation and illumination (and optionally moon altitude)
- 1–2 short suitability notes, e.g.:
  - “High and well-placed”
  - “Far from Moon”
  - “Good under bright Moon (cluster)”
  - “Large target; may not fit in FOV” (warning)

Explainability should be built from the computed features, not hardcoded strings.

---

## 8. CLI design (v1)

### 8.1 `plan` (implemented)
```
astrolabe plan
  --site <name|lat,lon>          (default site from config)
  --window <minutes>             (default 90)
  --start <iso8601>              (optional; default now)
  --mode <visual|imaging|quick>  (default visual)
  --min-alt <deg>                (default 30)
  --limit <N>                    (default 10)
  --format <text|json>           (default text)
```

Text output should be compact and readable. JSON output is for programmatic use and tests.

### 8.2 `update` (stub)
Purpose: prefetch optional datasets into cache.  
v1 behavior: prints what it *would* do; may create cache dir structure.

### 8.3 `doctor` (stub)
Purpose: validate environment + data availability for offline operation.  
v1 checks:
- config/site present
- curated catalog present and parseable
- ephemeris provider operational
- local time/timezone sanity

---

## 9. File and package layout (suggested)

```
astrolabe/
  planner/
    __init__.py
    core/
      models.py
      scoring.py
      compute.py
      explain.py
      planner.py
    providers/
      catalog.py
      ephemeris.py
      conditions.py   # stub
      cache.py
    cli/
      plan.py
      update.py       # stub
      doctor.py       # stub
  data/
    catalog_curated.csv
  tests/
    test_planner_smoke.py
    test_scoring_regression.py
```

---

## 10. Testing strategy

### 10.1 Deterministic regression tests
- Fix site (Adelaide), fixed time window (timezone-aware), fixed catalog subset.
- Assert top N target IDs in expected order (or within tolerances).
- Assert explainability fields exist and are within reasonable ranges.

### 10.2 Property tests (optional)
- Scores remain in [0, 100]
- If target never rises, it is never returned.
- If moon separation decreases, moon penalty should not improve (monotonicity expectation).

### 10.3 Smoke tests
- Planner runs with no network and with empty cache directory.

---

## 11. Key decisions (locked for v1)

1. v1 implements **operational planning** only; strategic/tactical are skeletons/stubs.
2. Planner is **opinionated**; avoid weight sliders/config complexity.
3. Catalog is **curated** for typical amateur equipment; quality over completeness.
4. Planner is **offline-first**; no runtime dependence on online services.
5. **Explainability is mandatory** in outputs.
6. `update` and `doctor` are at least sketched/stubbed early.

---

## 12. Open questions (for later, not blocking v1)

- How to define “typical equipment” presets (visual vs imaging)?
- Whether to ship multiple curated catalogs (urban vs dark site).
- Whether to include local site profiles in a config file or interactive wizard.
- Optional future: light pollution lookup during `update` to populate Bortle/SQM.

---

## 13. Implementation checklist (agent-friendly)

- [ ] Create data models in `planner.core.models`
- [ ] Implement local curated catalog loader
- [ ] Implement ephemeris provider (Sun/Moon position + illumination)
- [ ] Implement altitude computation and feature extraction
- [ ] Implement scoring with normalized components and curated weights
- [ ] Implement explainability builder
- [ ] Implement `astrolabe plan` CLI with text + json output
- [ ] Add `update` and `doctor` stubs (commands + basic structure)
- [ ] Add regression tests for Adelaide fixed window
- [ ] Ensure `plan` works offline and fast

---

*End of document.*
