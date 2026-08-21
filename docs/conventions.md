# Conventions

This document defines the core coordinate, unit, time, and domain-value conventions used throughout Astrolabe.

These conventions are architectural invariants.  
All modules must adhere to them.

---

# 1. Coordinate Frames

## 1.1 Internal Frame

Astrolabe uses **ICRS** coordinates internally.

All core logic — solving, goto refinement, polar alignment math, guiding math — operates in ICRS.

Reasons:

- Stable inertial reference frame
- Matches astronomical catalogs and plate-solver WCS outputs
- Time-invariant
- Enables reproducible tests

ICRS is close to historical FK5/J2000 coordinates, but they are not identical. Do not use `J2000` as a synonym for ICRS in code that depends on frame semantics.

Internal coordinates must never implicitly depend on observation time.

---

## 1.2 Mount Frames

Mount backends expose Astrolabe's canonical ICRS/radian contract regardless of the coordinate frame used by the hardware.

If a mount can consume and report the canonical frame directly, no time-dependent transformation should be introduced merely for uniformity.

For INDI mounts exposing `EQUATORIAL_EOD_COORD`, Astrolabe's current compatibility behaviour treats that coordinate as **FK5 mean equator/equinox of date**. This is a precessed mean coordinate, not a claim that the value is a full topocentric apparent/CIRS coordinate.

Conversion between ICRS and a mount-native epoch-of-date frame is performed **only at the mount backend boundary**. Core logic must not perform precession, nutation, or mount-frame conversion directly.

The standards implementation is an implementation detail of that mount-owned boundary. Third-party coordinate/frame objects must not leak into normal service APIs.

Changing the precise native-frame interpretation (for example, from FK5 equinox-of-date to CIRS/topocentric apparent coordinates) is a behavioural change and must be treated explicitly rather than hidden behind the word `JNow`.

---

# 2. Units

## 2.1 Internal Units

Canonical internal scalar units are explicit and simple:

- angular values: **radians**
- durations: **seconds**, unless a hardware contract explicitly names another unit such as guide-pulse milliseconds
- image positions/sizes: **pixels**

Angular values in radians include:

- Right Ascension
- Declination
- Hour angle
- Rotation angles
- Polar alignment corrections inside mathematical kernels
- Guiding errors inside mathematical kernels

No internal code should silently assume degrees.

---

## 2.2 External / User-Facing Units

Human-readable output should use:

- Degrees for large angles
- Arcseconds for small angular errors
- Sexagesimal input accepted where appropriate

CLI/config input must be converted to canonical units at an explicit boundary. Backend-native units such as INDI hours/degrees are converted inside that backend.

---

## 2.3 Domain Values Versus General Unit Objects

Astrolabe distinguishes **semantic type safety** from general dimensional arithmetic.

Use a small Astrolabe-owned domain type when values with the same physical dimensions have materially different meanings that must not be mixed. Coordinate-frame identity is the clearest example: an ICRS coordinate and an epoch-of-date mount coordinate are both pairs of radian angles but are not interchangeable.

For ordinary scalar quantities, prefer clear canonical units and unit-bearing field names such as:

- `exposure_s`
- `hfr_px`
- `pixel_scale_arcsec`
- `rms_arcsec`
- `ra_rad` / `dec_rad`

Do not introduce a general unit-bearing object merely to replace an already-unambiguous scalar contract. Plain floats and NumPy arrays remain appropriate inside contained numerical kernels where the unit and meaning are fixed by the API.

The practical rule is:

> Use domain types where semantic identity matters; use canonical named scalar units where dimensional meaning is already explicit; keep numerical kernels simple.

Third-party unit/frame objects are implementation tools, not Astrolabe's public domain vocabulary, unless a separate decision demonstrates enough leverage to justify exposing them.

---

# 3. Time

Astrolabe domain timestamps use:

- **UTC**, represented by timezone-aware datetimes

All time-dependent calculations must explicitly state the observation/equinox time being used. A frame transformation must reject naive or non-UTC datetime inputs rather than guessing their meaning.

A standards library may internally convert UTC to the timescale required by the astronomical model (for example TT for precession). That conversion remains inside the transformation boundary; it is not a reason to expose multiple timescales throughout service code.

---

# 4. Coordinate Conventions

## 4.1 Right Ascension

- Canonical range: [0, 2π)
- Wrap-safe comparisons required
- RA increases eastward

## 4.2 Declination

- Range: [-π/2, +π/2]

## 4.3 Latitude / Longitude

- Latitude: positive north
- Longitude: positive east
- Stored in degrees in config, converted to radians at the consuming domain boundary

---

# 5. Error Reporting

Pointing and guiding mathematical errors use radians internally unless a result contract explicitly names a presentation-oriented unit.

User-facing output should report:

- Angular errors in arcseconds
- RMS in arcseconds
- Drift rates in arcseconds per second

Result fields whose names include a unit suffix (for example `rms_arcsec`) carry that unit by contract and must not be treated as canonical-radian kernel values.

---

# 6. Precision

All angular calculations should use double precision floats.

Accumulated rounding errors must be avoided by:

- Normalizing RA after arithmetic
- Avoiding repeated degree ↔ radian conversions
- Converting between coordinate frames only at the owning boundary

---

# 7. Invariants

The following must always be true:

- Core logic uses ICRS and does not depend on mount frame conventions.
- Core logic does not implicitly depend on wall-clock time.
- Mount-native frame conversion occurs only at the mount boundary.
- Hardware-native unit conversion occurs inside the owning backend.
- All contained angular mathematical kernels use radians unless their API explicitly names another unit.
- Semantically distinct frames are not represented as interchangeable domain values at transformation boundaries.
- Third-party astronomy/unit objects do not spread through normal service APIs merely because a dependency provides them.
- All CLI output remains consistent across versions unless version-bumped.

---

These conventions are foundational to Astrolabe's architecture.

Any change to this document requires explicit discussion and version impact review.
