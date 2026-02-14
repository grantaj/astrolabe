# CLI Specification

This document defines Astrolabe’s command-line interface (CLI) surface.

The CLI is designed to be:
- scriptable
- deterministic
- stable across versions

The CLI layer must remain thin: parse args → call services → format output.

---

# 1. Command structure

Top-level:

```
astrolabe <command> [<subcommand>] [options]
```

Global options (available on all commands):

- `--config <path>`        Path to config file
- `--json`                 Emit machine-readable JSON output
- `--log-level <level>`    debug|info|warn|error
- `--timeout <seconds>`    Operation timeout (best-effort)
- `--dry-run`              Do not move mount; simulate actions where possible

---

# 2. Exit codes

- `0`  Success
- `1`  Recoverable failure (e.g., solve failed, star lost, timeout)
- `2`  Fatal failure (e.g., cannot connect to device, invalid config, internal error)

---

# 3. Output contract

## 3.1 Human output
Default output is concise, readable status messages.

## 3.2 JSON output (`--json`)
When `--json` is set, stdout must emit a single JSON object.

All JSON outputs must include:

- `ok` (bool)
- `command` (string)
- `timestamp_utc` (ISO-8601 string)
- `data` (object or null)
- `error` (object or null)

Error object (when ok=false):

- `code` (string)            stable reason identifier
- `message` (string)         human-readable summary
- `details` (object|null)    optional structured fields

The CLI must not emit other text to stdout in `--json` mode.
Logs may go to stderr.

---

# 4. Commands

## 4.1 `capture`

Capture a single frame from the configured camera.

```
astrolabe capture [options]
```

Options:
- `--exposure <seconds>` (required unless default configured)
- `--gain <value>`
- `--bin <n>`
- `--roi <x,y,w,h>`
- `--out <path>`   Save image to disk (optional)

JSON data (example fields):
- `path` (if saved)
- `exposure_s`
- `timestamp_utc`
- `width_px`, `height_px`

---

## 4.2 `solve`

Plate-solve a frame (default: last captured, or provided path).

```
astrolabe solve [<path>] [--in <path>]
```

Options:
- `<path>`             Input image path (optional)
- `--in <path>`        Input image path (optional, overrides positional)

JSON data:
- `success`
- `ra_rad`, `dec_rad`
- `pixel_scale_arcsec`
- `rotation_rad`
- `rms_arcsec`
- `num_stars`

---

## 4.3 `doctor`

System diagnostics for local dependencies and configuration.

```
astrolabe doctor
```

Options:
- `--json`           Emit machine-readable JSON output

Human output:
- A status report of config, INDI server connectivity, solver availability, and backend presence.

Exit codes:
- `0` when all checks pass
- `1` when any check fails

---

## 4.4 `mount`

Mount management and primitives.

### `mount connect`
```
astrolabe mount connect
```

### `mount status`
```
astrolabe mount status
```

JSON data:
- `connected`
- `ra_rad`, `dec_rad`
- `tracking`, `slewing`
- `timestamp_utc`

### `mount slew`
```
astrolabe mount slew --ra <hh:mm:ss|deg> --dec <dd:mm:ss|deg>
```

Options:
- `--ra <value>`   Sexagesimal or degrees
- `--dec <value>`  Sexagesimal or degrees

### `mount stop`
```
astrolabe mount stop
```

### `mount sync`
```
astrolabe mount sync --ra <...> --dec <...>
```

### `mount guide`
Pulse guide primitives (debug/useful for calibration).

```
astrolabe mount guide --ra-ms <ms> --dec-ms <ms>
```

---

## 4.5 `goto`

Closed-loop centering of a target.

```
astrolabe goto <target> [options]
```

Target forms:
- object name (catalog lookup, if enabled)
- explicit coordinates via `--ra/--dec`

Options:
- `--ra <...>` / `--dec <...>`    Explicit coordinates (bypass lookup)
- `--tolerance <arcsec>`          Default from config if omitted
- `--max-iter <n>`                Default from config if omitted

JSON data:
- `success`
- `iterations`
- `final_error_arcsec`

---

## 4.6 `polar`

Run polar alignment routine and output mechanical adjustment guidance.

```
astrolabe polar [options]
```

Options:
- `--ra-rotate-deg <deg>`   RA rotation amount for solving (default configured)

JSON data:
- `alt_correction_arcsec`
- `az_correction_arcsec`
- `residual_arcsec`
- `confidence`

Human output must include directionality (e.g., “raise ALT”, “move AZ east/west”)
based on configured hemisphere/site conventions.

---

## 4.7 `guide`

Guiding control.

### `guide calibrate`
```
astrolabe guide calibrate [options]
```

Options:
- `--duration <seconds>`

JSON data:
- calibration parameters (implementation-defined, stable keys once chosen)

### `guide start`
```
astrolabe guide start [options]
```

Options:
- `--aggression <0..1>`
- `--min-move <arcsec>`

### `guide status`
```
astrolabe guide status
```

JSON data:
- `running`
- `rms_arcsec`
- `star_lost`
- `last_error_arcsec`

### `guide stop`
```
astrolabe guide stop
```

---

## 4.8 `view`

Display FITS header and optionally render the image for inspection.

```
astrolabe view <path> [--show]
```

Options:
- `<path>`           Input FITS file path
- `--show`           Display image window (requires matplotlib)

# 5. Stability rules

- Command names and primary flags are stable once released.
- JSON field names are stable once released.
- Any breaking change requires a major version bump.

---

# 6. Safety

- `--dry-run` must never move the mount.
- Potentially hazardous operations must support `--timeout` and `mount stop`.
- Guiding must stop cleanly on errors (star lost, mount comms failure).
