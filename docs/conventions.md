# Conventions

This document defines the core coordinate, unit, and time conventions used throughout Astrolabe.

These conventions are architectural invariants.  
All modules must adhere to them.

---

# 1. Coordinate Frames

## 1.1 Internal Frame

Astrolabe uses **ICRS (J2000-equivalent)** coordinates internally.

All core logic — solving, goto refinement, polar alignment math, guiding math — operates in ICRS.

Reasons:

- Stable inertial reference frame
- Matches astronomical catalogs
- Matches plate solver WCS outputs
- Time-invariant
- Enables reproducible tests

Internal coordinates must never implicitly depend on observation time.

---

## 1.2 Mount Frame

Most mounts operate in **apparent coordinates (JNow)**.

Conversion from ICRS → apparent coordinates is performed **only at the mount backend boundary**.

Core logic must not perform precession or nutation calculations directly.

This isolates time-dependent math to a single location in the system.

---

# 2. Units

## 2.1 Internal Units

All angular values are stored internally in:

- **Radians**

This includes:
- Right Ascension
- Declination
- Hour angle
- Rotation angles
- Polar alignment corrections
- Guiding errors

No internal code should assume degrees.

---

## 2.2 External / User-Facing Units

Human-readable output should use:

- Degrees for large angles
- Arcseconds for small angular errors
- Sexagesimal input accepted where appropriate

CLI input must be converted to radians immediately after parsing.

---

# 3. Time

Astrolabe uses:

- **UTC** for all timestamps

UTC is sufficient for mount control, guiding, and plate solving.

Higher precision timescales (TT, TDB) are not required for MVP scope.

All time-dependent calculations (e.g., apparent coordinate conversion) must explicitly state the time being used.

---

# 4. Coordinate Conventions

## 4.1 Right Ascension

- Range: [0, 2π)
- Wrap-safe comparisons required
- RA increases eastward

## 4.2 Declination

- Range: [-π/2, +π/2]

## 4.3 Latitude / Longitude

- Latitude: positive north
- Longitude: positive east
- Stored in degrees in config, converted to radians internally

---

# 5. Error Reporting

All pointing and guiding errors are internally stored in radians.

User-facing output must report:

- Angular errors in arcseconds
- RMS in arcseconds
- Drift rates in arcseconds per second

---

# 6. Precision

All angular calculations should use double precision floats.

Accumulated rounding errors must be avoided by:

- Normalizing RA after arithmetic
- Avoiding repeated degree ↔ radian conversions

---

# 7. Invariants

The following must always be true:

- Core logic does not depend on mount frame conventions.
- Core logic does not depend on wall-clock time.
- All hardware-specific conversions occur in backend adapters.
- All internal math uses radians.
- All CLI output remains consistent across versions unless version-bumped.

---

These conventions are foundational to Astrolabe’s architecture.

Any change to this document requires explicit discussion and version impact review.
