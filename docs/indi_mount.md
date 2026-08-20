# INDI mount interaction reference

This document records **current Astrolabe mount/INDI behaviour** that is important enough not to leave implicit in implementation details. It is a reference, not a future implementation plan.

For public coordinate/unit conventions, see `conventions.md`. The mount capability exposes ICRS coordinates in radians; INDI-specific units and frame conversion remain private to the mount boundary.

## Coordinate property selection

Astrolabe probes for standard equatorial coordinate properties:

1. `EQUATORIAL_EOD_COORD` — epoch-of-date/apparent-style coordinates;
2. `EQUATORIAL_COORD` — J2000-style coordinates.

When the EOD property is used, Astrolabe converts between its canonical ICRS representation and the mount-native epoch-of-date representation at the mount boundary. When the J2000 property is available, no unnecessary time-dependent conversion is introduced.

## Slew semantics

INDI mount movement is property-driven. The important invariant is that `ON_COORD_SET` selects what a subsequent coordinate write means; setting it alone does not constitute the coordinate command.

For a slew Astrolabe currently:

1. ensures the mount is connected;
2. probes the supported coordinate property;
3. best-effort unparks the mount when the property exists;
4. best-effort enables tracking when supported;
5. arms `ON_COORD_SET` with `SLEW=On` and the other mutually exclusive actions off;
6. writes **RA and DEC atomically as one number vector**;
7. polls the selected coordinate property's state until it is no longer `Busy`, subject to a bounded timeout.

Atomic coordinate writes are a correctness requirement. Do not replace the vector write with separate RA and DEC commands.

INDI coordinate units at this boundary are:

- RA: hours;
- DEC: degrees.

Astrolabe converts to/from radians only at the backend boundary.

## Sync semantics

Sync uses the same coordinate-property and atomic-vector rules as slew, but arms `ON_COORD_SET.SYNC` rather than `SLEW` before writing coordinates.

A sync changes the mount's own coordinate mapping. Higher-level pointing code must not blindly learn the pre-sync discrepancy as an additional software correction or the same error would be compensated twice.

## State reads

`get_state()` uses an INDI device snapshot so coordinate, tracking and property-state values can be read from one coherent query rather than many sequential subprocess calls.

- EOD coordinates are converted back to ICRS before leaving the backend.
- `TELESCOPE_TRACK_STATE.TRACK_ON` supplies the tracking flag when present.
- the selected equatorial property's `_STATE` is treated as the slew-state indication; `Busy` means slewing.

## Current time/location caution

Astrolabe does **not** currently write `TIME_UTC` or `GEOGRAPHIC_COORD` during each slew. Some simulator builds have behaved badly when those values are pushed programmatically in this path. Any future explicit mount-initialization policy should be designed and tested separately rather than hidden inside `slew_to()`.

## Failure and capability behaviour

Optional INDI properties are probed rather than assumed. Park, abort, tracking and pulse-guide operations are capability-dependent and remain mount-backend concerns.

Further control-plane performance work, including whether capability probing should be cached or a broader persistent INDI client is justified, is tracked in GitHub issue #67. That future issue does not change the current invariants above.
