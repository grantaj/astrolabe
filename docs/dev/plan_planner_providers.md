# Astrolabe Planner — Providers & Update Strategy (v1)

**Project:** Astrolabe  
**Component:** Planner (offline-first)  
**Document purpose:** Define provider architecture and update data sources for v1 implementation.

This document accompanies `astrolabe_planner_v1_planning.md` and focuses specifically on:
- Provider architecture
- Offline-first guarantees
- Data sources for `update`
- Decision to use OpenNGC for catalog ingestion
- Weather strategy (stubbed in v1)

---

## Implementation Audit

**Status:** Partially implemented on `origin/main`.

Implemented:
- `plan` is offline-first in normal operation and uses local providers/data.
- `CatalogProvider` and `LocalCuratedCatalogProvider` exist.
- `astrolabe update catalog` downloads OpenNGC source files, caches them under `~/.astrolabe/cache/catalog/opengnc/<version>/`, writes metadata, and generates `data/catalog_curated.csv` by default.
- Built-in ephemeris-style code exists for Sun/Moon calculations and approximate solar-system targets.
- Planner core consumes normalized `Target` models rather than raw file/network data.

Stale or different from implementation:
- OpenNGC defaults to `master`, not a pinned release or commit.
- Provider architecture is minimal; there is no `EphemerisProvider`, `ConditionsProvider`, `CachedProvider`, or `FallbackProvider` abstraction yet.
- Weather/conditions are not represented by a `NullConditionsProvider`; they are absent.
- The planner currently adds solar-system targets through a helper function rather than through a provider stack returned by `get_catalog_providers`.
- Light pollution lookup/update remains deferred; only config-provided SQM/Bortle are used.

Still todo:
- Decide whether to pin OpenNGC updates for reproducibility.
- Add a conditions provider interface if planner scoring should eventually use live/measured conditions.
- Add provider-level tests for update/cache/fallback behavior.
- Clarify whether solar-system targets should become a normal provider or remain a special planner helper.

---

# 1. Core Philosophy

Astrolabe is **offline-first**.

Observing typically occurs without reliable internet access. Therefore:

- `astrolabe plan` must **never require network access**.
- All required astronomical data must be available locally.
- Online data is optional enrichment only.
- `update` is the only command allowed to access the network.

Providers must be structured so that the planner core is entirely decoupled from:
- HTTP calls
- External APIs
- File formats
- Network failure modes

The planner core consumes **normalized internal models only**.

---

# 2. Provider Architecture

Providers are adapters that fetch or load data and convert it into internal domain models.

Planner core never knows where data came from.

## 2.1 Separation of concerns

```
planner.core       → pure scoring & computation (no IO)
planner.providers  → data acquisition + caching
planner.cli        → command orchestration
```

Planner receives:

- `list[Target]`
- `EphemerisProvider`
- `ConditionsProvider`
- `SiteProfile`
- `TimeWindow`

No provider should embed scoring logic.

---

# 3. v1 Provider Set (Minimal, Reliable)

## 3.1 Catalog Provider

### Decision: Use OpenNGC as canonical upstream source

**Source:**  
OpenNGC GitHub repository  
https://github.com/mattiaverga/OpenNGC  
License: CC BY-SA 4.0

### Why OpenNGC?

- Clean, machine-readable
- Widely used in astronomy tooling
- Explicit licensing
- Includes NGC, IC, Messier cross-mapping
- Southern sky coverage

This becomes the **authoritative upstream dataset**.

---

## 3.2 Catalog Update Strategy

### `astrolabe update catalog`

Steps:

1. Download OpenNGC release (pinned version or commit hash).
2. Store raw data in cache directory:
   ```
   ~/.astrolabe/cache/catalog/opengnc/<version>/
   ```
3. Generate curated subset:
   - Filter by:
     - Object type
     - Magnitude threshold
     - Angular size limits
     - Southern hemisphere relevance
   - Optionally include manually tagged “southern_showpiece” objects.
4. Output generated artifact:
   ```
   astrolabe/data/catalog_curated.csv
   ```

Important:

- The curated catalog file is committed into the repository.
- Planner works even if `update` has never been run.
- Update is reproducible via pinned OpenNGC version.

---

## 3.3 Ephemeris Provider (v1)

### Use Built-In Offline Computation

- Approximate Sun position
- Approximate Moon position
- Moon illumination fraction

No JPL downloads required in v1.

Later enhancement:
- Optional JPL ephemeris file provider behind same interface.

---

## 3.4 Weather / Conditions Provider (v1)

### Decision: Stub Only

Weather is not required for operational planning in v1.

Implement:

- `NullConditionsProvider`
  - Returns `ConditionsProfile()` with all fields None.
- Optional CLI override:
  - `--conditions good|mixed|bad`

No live weather fetching.
No forecast API integration.
No BoM integration in v1.

Rationale:

- Avoid brittle API dependencies.
- Keep planner deterministic.
- Focus on geometric/astronomical scoring first.

Weather can later influence:
- Strategic layer (trip viability)
- Tactical layer (is tonight worth setting up?)

It must never block `plan`.

---

# 4. Future-Ready Provider Interfaces

Even though v1 only implements local providers, interfaces must support:

- `CachedProvider`
- `FallbackProvider`
- `OnlineCatalogProvider`
- `ForecastConditionsProvider`

But these remain unused in v1.

This ensures future expansion does not require redesign of planner core.

---

# 5. Caching Strategy

## 5.1 Catalog

- Raw OpenNGC stored in cache.
- Curated derived catalog stored in repo.
- Cache versioned by upstream release tag or commit hash.

## 5.2 Weather (future)

- Cached per-site per-date JSON.
- TTL-based (e.g. 6–12 hours).
- Planner never depends on its presence.

## 5.3 Ephemeris

- No caching required in v1.
- Computed at runtime.

---

# 6. Provider Selection Rules

Provider stack is assembled in CLI layer.

Example (v1):

```
CatalogProvider      → LocalCuratedCatalogProvider
EphemerisProvider    → BuiltInEphemerisProvider
ConditionsProvider   → NullConditionsProvider
```

Planner core receives only resolved data.

---

# 7. What We Are Explicitly NOT Doing in v1

- No SIMBAD integration
- No full NGC ingestion at runtime
- No Open-Meteo integration
- No BoM API calls
- No real-time weather dependency
- No scraping of light pollution tiles
- No runtime HTTP calls during `plan`

---

# 8. Light Pollution / Bortle (Deferred)

Future enhancement:

- Use a light pollution dataset lookup during `update`
- Store SQM/Bortle inside `SiteProfile`
- Cache permanently

Not required for v1.

---

# 9. Summary of Decisions

1. Planner is strictly offline during operation.
2. `update` is the only network-enabled command.
3. OpenNGC is the canonical catalog upstream.
4. Curated catalog is generated and committed.
5. Weather is stubbed in v1.
6. Providers are cleanly separated from planner core.
7. Provider interfaces anticipate future online enhancements.
8. Determinism and reliability take precedence over data completeness.

---

# 10. v1 Implementation Checklist (Providers)

- [ ] Implement `LocalCuratedCatalogProvider`
- [ ] Implement `BuiltInEphemerisProvider`
- [ ] Implement `NullConditionsProvider`
- [ ] Implement `update catalog` command (OpenNGC ingestion + curation pipeline)
- [ ] Implement provider interface abstractions
- [ ] Ensure `plan` works without network and without cache

---

*End of document.*
