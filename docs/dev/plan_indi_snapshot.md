# INDI Client Snapshot Query Plan

Goal: reduce TCP connection churn between `IndiClient` and `indiserver` by adding a batch-query method that fetches all device properties in a single `indi_getprop` invocation, and refactoring `IndiMountBackend.get_state()` to use it.

Date: 2026-02-23

---

## 1. Motivation

### 1.1 The problem

`IndiClient` communicates with `indiserver` by spawning a new `indi_getprop` or `indi_setprop` subprocess for every operation. Each subprocess opens a TCP connection, sends its query, reads the response, and exits — closing the socket.

When the subprocess exits, the OS tears down the TCP socket. If `indiserver` is still pushing property updates to that client, the server's `read()` hits a closed socket and logs:

```
Client 9: read: Connection reset by peer
```

These messages are harmless but noisy. In the integration test container they obscure real output and are confusing.

### 1.2 Scale of the problem

A single `IndiMountBackend.get_state()` call currently makes **7 sequential subprocess invocations**:

| # | Method | Query |
|---|--------|-------|
| 1 | `has_prop` | `EQUATORIAL_EOD_COORD.RA` |
| 2 | `has_prop` | `EQUATORIAL_COORD.RA` |
| 3 | `getprop_value` | `EQUATORIAL_EOD_COORD.RA` |
| 4 | `getprop_value` | `EQUATORIAL_EOD_COORD.DEC` |
| 5 | `has_prop` | `TELESCOPE_TRACK_STATE.TRACK_ON` |
| 6 | `getprop_value` | `TELESCOPE_TRACK_STATE.TRACK_ON` |
| 7 | `getprop_state` | `EQUATORIAL_EOD_COORD` |

The `test_indi_mount_slew_and_state` integration test calls `get_state()` in a polling loop with 0.5 s sleeps, plus additional `getprop_value` calls for `TARGET_EOD_COORD`. Over a 60-second slew timeout this produces **hundreds** of short-lived TCP connections, each generating a "Connection reset by peer" log line.

`slew_to()` adds another 5+ `has_prop` calls for capability probing. Other methods (`sync`, `pulse_guide`, `set_tracking`) follow the same pattern.

### 1.3 INDI scripting tools support batch queries

The `indi_getprop` documentation (see `indi_scripting.html`) states:

> Any component may be `"*"` to match all.

A single wildcard query like `"Telescope Simulator.*.*"` returns **all** element values for the device in one TCP connection. Output format without `-1`:

```
Telescope Simulator.EQUATORIAL_EOD_COORD.RA=6.0
Telescope Simulator.EQUATORIAL_EOD_COORD.DEC=45.0
Telescope Simulator.TELESCOPE_TRACK_STATE.TRACK_ON=On
Telescope Simulator.CONNECTION.CONNECT=On
...
```

Additionally, `indi_getprop` supports a `_STATE` pseudo-element:

> Set element to `_STATE` to report state.

So `"Telescope Simulator.*._STATE"` returns property states in one invocation:

```
Telescope Simulator.EQUATORIAL_EOD_COORD._STATE=Ok
Telescope Simulator.TELESCOPE_TRACK_STATE._STATE=Idle
...
```

`indi_getprop` accepts multiple query arguments, so both can be combined into a single invocation:

```
indi_getprop "Telescope Simulator.*.*" "Telescope Simulator.*._STATE"
```

This yields all element values **and** all property states in one TCP connection.

---

## 2. Design

### 2.1 New method: `IndiClient.snapshot`

Add a single method to `IndiClient` that returns a parsed snapshot of all properties for a given device.

```python
def snapshot(
    self, device: str, *, timeout_s: float = 2.0
) -> dict[str, str]:
```

Invokes:

```
indi_getprop -h HOST -p PORT -t TIMEOUT "DEVICE.*.*" "DEVICE.*._STATE"
```

Parses each output line as `key=value` (splitting on the first `=`) and returns a flat dict:

```python
{
    "Telescope Simulator.EQUATORIAL_EOD_COORD.RA": "6.0",
    "Telescope Simulator.EQUATORIAL_EOD_COORD.DEC": "45.0",
    "Telescope Simulator.EQUATORIAL_EOD_COORD._STATE": "Ok",
    "Telescope Simulator.TELESCOPE_TRACK_STATE.TRACK_ON": "On",
    "Telescope Simulator.TELESCOPE_TRACK_STATE._STATE": "Idle",
    ...
}
```

The `-1` flag is **not** used (it is only valid for single-result queries).

### 2.2 Refactor `IndiMountBackend.get_state`

Replace the 7 sequential subprocess calls with:

1. One `self._client.snapshot(self.device)` call.
2. Pure dict lookups for `has_prop`, `getprop_value`, and `getprop_state` equivalents.

```python
def get_state(self) -> MountState:
    if not self._connected:
        self.connect()

    snap = self._client.snapshot(self.device)
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    ra_key_jnow = f"{self.device}.EQUATORIAL_EOD_COORD.RA"
    ra_key_j2000 = f"{self.device}.EQUATORIAL_COORD.RA"
    # ... dict lookups instead of subprocess calls ...
```

This reduces `get_state()` from 7 TCP connections to **1**.

### 2.3 Scope limitation

This plan **only** changes the read path (`get_state`). Write operations (`setprop`, `setprop_multi`, `setprop_vector`) remain as individual subprocess calls — they are inherently one-shot commands and cannot be batched.

The `has_prop` calls in `slew_to()`, `sync()`, and other write-oriented methods are not changed in this plan. They are candidates for future optimisation (e.g., caching capability probing results at `connect()` time, as suggested in `plan_indi.md` §4.2). That is a separate concern.

### 2.4 Design decisions

- **No caching / staleness**: `snapshot()` is a fresh query each time it is called. No state is held between calls. This preserves the stateless, simple nature of the current `IndiClient`.
- **No new dependencies**: continues to use `subprocess.run` and `indi_getprop`.
- **Backwards compatible**: existing `has_prop`, `getprop_value`, `getprop_state` methods remain unchanged. Other callers (camera backend, scripts) continue to work.
- **Wildcard safety**: the device name is interpolated into the query string. Device names with glob metacharacters are not expected in practice. No shell expansion occurs because `subprocess.run` is called with a list (not a shell string).

---

## 3. Files modified

| File | Change |
|------|--------|
| `astrolabe/indi/client.py` | Add `snapshot()` method |
| `astrolabe/mount/indi.py` | Refactor `get_state()` to use `snapshot()` |
| `tests/mount/test_indi_mount.py` | Update unit tests that verify `get_state()` behaviour |

No new files are created. No files are deleted.

---

## 4. `IndiClient.snapshot` implementation

```python
def snapshot(self, device: str, *, timeout_s: float = 2.0) -> dict[str, str]:
    """Fetch all property values and states for a device in one query."""
    cp = subprocess.run(
        [
            "indi_getprop",
            "-h", self.host,
            "-p", str(self.port),
            "-t", str(timeout_s),
            f"{device}.*.*",
            f"{device}.*._STATE",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    result: dict[str, str] = {}
    for line in cp.stdout.splitlines():
        eq = line.find("=")
        if eq < 0:
            continue
        result[line[:eq]] = line[eq + 1:]
    return result
```

Notes:
- `check=False` because exit code 1 means "at least one query returned nothing" — the `_STATE` query may not match all properties, which is acceptable.
- Lines without `=` (malformed output) are silently skipped.

---

## 5. `get_state` refactored implementation

```python
def get_state(self) -> MountState:
    if not self._connected:
        self.connect()

    snap = self._client.snapshot(self.device)
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    jnow_ra_key = f"{self.device}.EQUATORIAL_EOD_COORD.RA"
    j2000_ra_key = f"{self.device}.EQUATORIAL_COORD.RA"
    has_jnow = jnow_ra_key in snap
    has_j2000 = j2000_ra_key in snap

    ra_rad = None
    dec_rad = None

    if has_jnow:
        ra_jnow = _hours_to_rad(float(snap[jnow_ra_key]))
        dec_jnow = _degrees_to_rad(
            float(snap[f"{self.device}.EQUATORIAL_EOD_COORD.DEC"])
        )
        ra_rad, dec_rad = jnow_to_icrs(ra_jnow, dec_jnow, now_utc)
    elif has_j2000:
        ra_rad = _hours_to_rad(float(snap[j2000_ra_key]))
        dec_rad = _degrees_to_rad(
            float(snap[f"{self.device}.EQUATORIAL_COORD.DEC"])
        )

    track_key = f"{self.device}.TELESCOPE_TRACK_STATE.TRACK_ON"
    tracking = snap.get(track_key, "").lower() == _INDI_ON.lower()

    slewing = False
    if has_jnow:
        state_key = f"{self.device}.EQUATORIAL_EOD_COORD._STATE"
    elif has_j2000:
        state_key = f"{self.device}.EQUATORIAL_COORD._STATE"
    else:
        state_key = None

    if state_key is not None:
        slewing = snap.get(state_key, "").lower() == _INDI_BUSY.lower()

    return MountState(
        connected=True,
        ra_rad=ra_rad,
        dec_rad=dec_rad,
        tracking=tracking,
        slewing=slewing,
        timestamp_utc=now_utc,
    )
```

---

## 6. Test changes

### 6.1 Existing unit tests affected

The following tests patch `IndiClient` methods called by `get_state()`:

- `test_get_state_jnow`
- `test_get_state_detects_slewing`
- `test_get_state_j2000`
- `test_get_state_auto_connects`

These currently patch `has_prop`, `getprop_value`, and `getprop_state`. They must be updated to patch `snapshot` instead, providing a dict return value.

### 6.2 Updated test pattern

Before (current):
```python
def test_get_state_jnow(mount):
    mount._connected = True
    with (
        patch("...IndiClient.has_prop") as mock_has_prop,
        patch("...IndiClient.getprop_value") as mock_getprop,
        patch("...IndiClient.getprop_state") as mock_getprop_state,
        patch("...jnow_to_icrs") as mock_jnow_to_icrs,
    ):
        # ... configure side_effect functions for each mock ...
```

After:
```python
def test_get_state_jnow(mount):
    mount._connected = True
    snap = {
        "Telescope Simulator.EQUATORIAL_EOD_COORD.RA": "6.0",
        "Telescope Simulator.EQUATORIAL_EOD_COORD.DEC": "45.0",
        "Telescope Simulator.EQUATORIAL_EOD_COORD._STATE": "Ok",
        "Telescope Simulator.TELESCOPE_TRACK_STATE.TRACK_ON": "On",
    }
    with (
        patch("...IndiClient.snapshot", return_value=snap),
        patch("...jnow_to_icrs") as mock_jnow_to_icrs,
    ):
        # ... same assertions, simpler setup ...
```

### 6.3 New unit test for `snapshot`

Add a test in `tests/indi/test_client.py` (or within the mount test file) that verifies `snapshot()` correctly parses multi-line `indi_getprop` output into a dict.

### 6.4 Integration tests unchanged

The integration tests (`test_indi_mount_slew_and_state`, `test_indi_mount_connect_and_state`) are not modified. They exercise the real code path and will automatically benefit from the reduced connection churn.

---

## 7. Impact on connection churn

### Before

| Operation | Subprocess calls |
|-----------|-----------------|
| `get_state()` | 7 |
| `get_state()` in slew poll (×~20 iterations) | 140 |
| `slew_to()` | ~10 |
| **Total for `test_indi_mount_slew_and_state`** | **~150+** |

### After

| Operation | Subprocess calls |
|-----------|-----------------|
| `get_state()` | 1 |
| `get_state()` in slew poll (×~20 iterations) | 20 |
| `slew_to()` (unchanged) | ~10 |
| **Total for `test_indi_mount_slew_and_state`** | **~30** |

**~80% reduction** in TCP connections opened and torn down. Proportional reduction in "Connection reset by peer" log messages from `indiserver`.

---

## 8. Risks & mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Wildcard query returns too much data | Slower parse for devices with many properties | Telescope simulators have ~30-50 properties. Parse is trivial. |
| `_STATE` pseudo-element not supported on older INDI | Missing state keys in snapshot dict | `snap.get(state_key, "")` defaults gracefully; slewing defaults to `False`. |
| Device name contains glob metacharacters | Query matches wrong device | Not expected in practice. `subprocess.run` with list args avoids shell expansion. |
| Snapshot is stale by the time values are read | Coordinates slightly out of date | Same staleness window as current sequential calls (actually better — all values are from the same point in time). |

---

## 9. Future work (out of scope)

- **Capability caching at connect time**: `slew_to()`, `sync()`, and other methods probe `has_prop` on every call. These capabilities don't change during a session. Caching them at `connect()` time (as suggested in `plan_indi.md` §4.2) would further reduce churn. This is a separate concern.
- **Entrypoint stderr suppression**: redirecting `indiserver` stderr to a log file (Option B from the earlier analysis) would eliminate remaining noise from `setprop` calls. Complementary to this change.
- **Persistent INDI XML client**: replacing subprocess-per-call with a long-lived TCP connection is the architectural end-state but is a much larger undertaking.
