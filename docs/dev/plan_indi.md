# INDI Shared Layer Plan

Goal: structure shared INDI plumbing before implementing mount backends (simulator + EQMod), avoiding duplicate INDI abstractions while keeping Astrolabe's backend interfaces intact.

Date: 2026-02-19

---

## 1. Inventory (current state)

Common INDI usage patterns:
- Subprocess calls to `indi_getprop` / `indi_setprop` with host/port, timeout, `-1`.
- Device discovery by polling `indi_getprop` output for `"{device}."`.
- Property existence probing (`has_prop`).
- Soft vs hard property setting (ignore missing optional props).
- Timeout-based polling for device readiness and file updates.

Camera-specific usage:
- CCD properties: `CCD_GAIN.*`, `CCD_BINNING.*`, `CCD_FRAME.*`, `CCD_EXPOSURE.*`, `GUIDER_EXPOSURE.*`.
- File upload controls: `UPLOAD_MODE.*`, `UPLOAD_SETTINGS.*`, `CCD_FILE_PATH.*`.
- FITS readiness via file mtime.

Script duplication:
- `scripts/gen_sim_fits.py` re-implements `indi_getprop` / `indi_setprop` helpers and device discovery.

No QHY-specific backend exists; QHY is an INDI device name passed to the INDI backend.

---

## 2. Proposed shared INDI utility layer (minimal)

Location:
- `astrolabe/indi/client.py` (preferred) or `astrolabe/indi/util.py`.

Scope:
- Thin transport/util helpers only. Do **not** model device capabilities or introduce a new abstraction over INDI device semantics.

Option A: pure functions
- `run_indi(tool, host, port, args, *, check=True, capture=False) -> CompletedProcess`
- `getprop_value(host, port, query, *, timeout_s=2.0) -> str`
- `has_prop(host, port, query, *, timeout_s=2.0) -> bool`
- `setprop(host, port, prop, value, *, soft=True) -> None`
- `wait_for_device(host, port, device, *, timeout_s=10.0) -> None`
- (optional) `list_props(host, port, *, timeout_s=2.0) -> str`

Option B: tiny class wrapper (recommended)
- `IndiClient(host, port)` with methods mirroring Option A.

Optional helper:
- `IndiDevice(client, name)` with `prop(suffix)` to format `"{device}.{suffix}"`.
- Keep device-specific behavior in the backend (camera/mount).

---

## 3. Map current camera backend to shared layer (no code yet)

Current `astrolabe/camera/indi.py` helpers to migrate:
- `_run_indi`, `_getprop_value`, `_has_prop`, `_setprop`, `_wait_for_device`.

Refactor plan:
- Replace helper calls with `IndiClient` (or module functions).
- Keep camera-specific logic (gain, binning, ROI, upload settings, exposure) in `IndiCameraBackend`.
- Preserve existing retry logic for `CCD_FILE_PATH` and file mtime checks.

Tests impacted:
- `tests/camera/test_indi_camera.py` patch targets change from local helper functions to `IndiClient` methods or module functions.
- Keep tests focused on property-setting behavior, not subprocess correctness.

Scripts:
- Optionally update `scripts/gen_sim_fits.py` to reuse shared helpers, or leave it standalone if we want to keep scripts independent from package modules.

---

## 4. Mount backend usage (simulator + EQMod)

Expected shared usage:
- `IndiClient.wait_for_device(device)` during connect.
- `IndiClient.setprop(f"{device}.CONNECTION.CONNECT", "On")` and disconnect variant.
- `has_prop` probing for optional properties (e.g., tracking, slew states, guide rates).

Likely INDI telescope properties (to confirm against device driver output):
- Connection: `CONNECTION.CONNECT` / `CONNECTION.DISCONNECT`
- Slew: `EQUATORIAL_EOD_COORD` or `EQUATORIAL_COORD` (device dependent)
- Sync: `EQUATORIAL_EOD_COORD` with `ON_COORD_SET.SYNC` (or driver-specific)
- Tracking: `TELESCOPE_TRACK_STATE`
- Park: `TELESCOPE_PARK`
- Pulse guide: `TELESCOPE_TIMED_GUIDE_WE` / `TELESCOPE_TIMED_GUIDE_NS`

Plan: probe device properties at runtime to choose supported commands (similar to how camera chooses `CCD_GAIN.GAIN` vs `CCD_GAIN.VALUE`).

### 4.1 Mount property mapping (draft)

MountBackend method -> INDI property mapping (probe in this order):

1. `connect()`:
- `CONNECTION.CONNECT=On` (if property exists)
- Optional: verify `CONNECTION` state by reading the switch state.

2. `disconnect()`:
- `CONNECTION.DISCONNECT=On` (if property exists)

3. `slew_to(ra_rad, dec_rad)`:
- Preferred: `EQUATORIAL_EOD_COORD.RA` / `.DEC` with `ON_COORD_SET.SLEW=On`
- Fallback: `EQUATORIAL_COORD.RA` / `.DEC` with `ON_COORD_SET.SLEW=On`
- Note: Units are hours/degrees in INDI; convert from radians at backend boundary.

4. `sync(ra_rad, dec_rad)`:
- Preferred: `EQUATORIAL_EOD_COORD` + `ON_COORD_SET.SYNC=On`
- Fallback: `EQUATORIAL_COORD` + `ON_COORD_SET.SYNC=On`

5. `get_state()`:
- Read from `EQUATORIAL_EOD_COORD` if present, else `EQUATORIAL_COORD`
- `TRACK_STATE` / `TELESCOPE_TRACK_STATE` for tracking flag (driver-specific)
- `TELESCOPE_SLEW_STATE` or `EQUATORIAL_*` state indicators if present

6. `park()`:
- `TELESCOPE_PARK.PARK=On` if available

7. `stop()`:
- `TELESCOPE_ABORT_MOTION.ABORT=On` if available (common across drivers)

8. `pulse_guide(ra_ms, dec_ms)`:
- `TELESCOPE_TIMED_GUIDE_WE` for RA (W/E) durations
- `TELESCOPE_TIMED_GUIDE_NS` for DEC (N/S) durations
- Set only the needed direction with non-zero duration.

### 4.2 Capability probing strategy

At `connect()` time:
- Cache which coordinate property is supported: `EQUATORIAL_EOD_COORD` vs `EQUATORIAL_COORD`.
- Cache availability of `ON_COORD_SET`, `TELESCOPE_PARK`, `TELESCOPE_ABORT_MOTION`,
  `TELESCOPE_TRACK_STATE`, `TELESCOPE_TIMED_GUIDE_WE/NS`.
- Expose internal booleans (e.g., `_has_abort`, `_has_park`) to choose behavior at runtime.

### 4.3 Simulator vs EQMod notes (expected)

- Simulator and EQMod both commonly expose `EQUATORIAL_EOD_COORD` and `ON_COORD_SET`.
- Some drivers expose `TELESCOPE_TRACK_STATE` while others use `TRACK_STATE` or a state flag on the coordinate property.
- Pulse guide properties may be missing on simulator drivers; probe and no-op with a warning if absent.

---

## 5. Implementation sequencing + validation

Sequencing:
1. Add shared INDI utility module (`astrolabe/indi/client.py`).
2. Migrate camera backend to use shared helpers.
3. Update tests to patch the new helper API.
4. (Optional) Update scripts to reuse shared helpers.
5. Implement mount backend using shared helpers, with property probing.

Validation:
- Unit: existing camera tests updated and passing.
- Integration: manual smoke test with INDI simulator (`scripts/setup_indi_simulators.sh`) and a capture command.
- Mount (when added): connect/disconnect, basic slew/sync/park/pulse guide smoke checks.

## Decision: module location

We will place shared INDI helpers under `astrolabe/indi/` (e.g., `astrolabe/indi/client.py`) to keep transport-level INDI utilities separate from `camera/` and `mount/` and avoid circular dependencies.

## Decision: IndiClient vs pure functions

We will implement a tiny `IndiClient` class (rather than pure functions) to encapsulate host/port, simplify backend wiring, and make tests patching simpler. The class remains a thin wrapper over `indi_getprop`/`indi_setprop` with no additional abstraction of device semantics.
