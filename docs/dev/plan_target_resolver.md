# Target Resolver v1 — Implementation Plan

**Goal:** Resolve user input (names, catalog IDs, aliases) to RA/Dec offline-first, with fuzzy matching and deterministic ranking.

---

## Implementation Audit

**Status:** Implemented in the pointing branch / PR #30 (`origin/4-pointing`), but not present on `origin/main` at the time of this audit.

Implemented in `origin/4-pointing`:
- `astrolabe/services/target/` exists with resolver, index, parser, normalization, types, and update helpers.
- `TargetResolver.resolve()` supports exact ID, exact alias, parsed Bayer/Flamsteed, and fuzzy fallback.
- Resolver input data exists for core DSO catalog rows, Hipparcos subset rows, proper-name aliases, Bayer/Flamsteed aliases, and optional BSC crosswalk aliases.
- Repo data includes `data/hip_subset.csv`, `data/star_aliases.csv`, and `data/bayer_flamsteed.csv`.
- Catalog update helpers exist for Hipparcos subset and BSC crosswalk generation.
- Unit tests exist under `tests/target/`.

Stale or different from implementation:
- The resolver is implemented as a service layer, not inside `astrolabe/planner`.
- Config-driven resolver catalog selection and `hip_max_mag` are not fully wired through runtime config in the implementation inspected.
- Alias coverage depends on backing HIP records in `hip_subset.csv`; aliases without backing records are ignored rather than resolved online.

Still todo:
- Reconcile this document after PR #30 lands on `main`.
- Document resolver CLI behavior alongside implementation once the command surface is stable.
- Expand tests around missing alias backing records and catalog update reproducibility.

---

## 1. Scope

**In scope (v1):**
- Resolve DSO IDs and names from OpenNGC curated catalog.
- Resolve bright stars from a Hipparcos subset (mag <= 7.0 default).
- Proper-name alias table (IAU names -> HIP ID).
- Bayer/Flamsteed parser + crosswalk (e.g., "alpha cen", "beta cen", "61 cyg").
- Fuzzy fallback for spelling mistakes.

**Out of scope (v1):**
- Full SIMBAD queries, online lookups.
- Tycho2/GSC ingestion for resolver.

---

## 2. Catalog Strategy

### 2.1 Default catalogs
- `core_dso`: OpenNGC curated subset (already in update catalog flow).
- `hip_subset`: Hipparcos filtered by `hip_max_mag` (default 7.0).
- `star_aliases`: Proper-name aliases -> HIP IDs.
- `bayer_flamsteed`: Bayer/Flamsteed crosswalk -> HIP IDs.

### 2.2 Configurability
Add `[resolver]` section:

```toml
[resolver]
catalogs = ["core_dso", "hip_subset", "star_aliases", "bayer_flamsteed"]
hip_max_mag = 7.0
min_score = 0.7
```

- Catalog order defines priority.
- If `hip_max_mag` changes, rerun `update catalog` to regenerate `hip_subset`.

---

## 3. Files and Layout

### 3.1 New code (services)
```
astrolabe/services/target/
  __init__.py
  resolver.py
  index.py
  normalize.py
  parser.py
  types.py
```

### 3.2 New data (repo-checked-in)
```
data/
  hip_subset.csv
  star_aliases.csv
  bayer_flamsteed.csv
```

### 3.3 Update pipeline
```
scripts/catalog/
  build_hip_subset.py
  build_bayer_flamsteed.py
```

---

## 4. Data Formats

### 4.1 core_dso (data/catalog_curated.csv)
Reuse existing planner curated catalog columns:
- `id`, `name`, `common_name`, `messier_id`, `caldwell_id`
- `ra_deg`, `dec_deg`, `type`, `mag`
- `size_arcmin`, `size_major_arcmin`, `size_minor_arcmin`
- `surface_brightness`, `tags`

Resolver will treat these as:
- `id` = `id` (e.g., NGC/IC)
- aliases from `common_name`, `messier_id`, `caldwell_id`, and `name`

### 4.2 hip_subset.csv
Columns:
- `hip_id`
- `ra_deg`
- `dec_deg`
- `mag`
- `name` (optional)

### 4.3 star_aliases.csv
Columns:
- `alias`
- `hip_id`

### 4.4 bayer_flamsteed.csv
Columns:
- `alias`
- `hip_id`

---

## 5. Matching Pipeline

1. Normalize query (casefold, punctuation strip, whitespace collapse).
2. Exact ID match (M/NGC/IC/HIP).
3. Proper name alias match (IAU names).
4. Bayer/Flamsteed parse -> crosswalk.
5. Fuzzy match (last resort).

Ranking:
- exact ID: 1.0
- exact alias: 0.95
- parsed Bayer/Flamsteed: 0.9
- fuzzy: 0.5–0.85

Return top N (default 5) with scores + reasons.

---

## 6. Resolver API

```python
class TargetResolver:
    def resolve(self, query: str, limit: int = 5) -> list[TargetMatch]
```

`TargetMatch` includes:
- `id`, `name`, `ra_deg`, `dec_deg`
- `match_score`, `match_reason`

---

## 7. Update Catalog Integration

`astrolabe update catalog` should:
- download OpenNGC (existing flow)
- fetch Hipparcos source
- generate `hip_subset.csv` using `hip_max_mag`
- generate `bayer_flamsteed.csv`
- leave full HIP in cache

---

## 8. Open Decisions

- Source for IAU proper-name aliases (manual list vs generated)
- Exact columns available from HIP source
- Whether to include Messier/NGC alias expansion in curated OpenNGC export

---
