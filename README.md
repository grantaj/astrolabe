# Astrolabe

Astrolabe is a minimal, Linux-first command-line tool for telescope mount control, plate solving, polar alignment, and guiding.

It is designed to be small, scriptable, deterministic, and reliable — not a full imaging suite or planetarium replacement.

Astrolabe focuses on doing a small number of things well.

---

## Philosophy

Astrolabe is:

- CLI-first
- Modular (camera, solver, mount backends are swappable)
- Scriptable (`--json` output for automation)
- Deterministic (clear exit codes, explicit failure states)
- Lightweight

Astrolabe is not:

- A GUI application
- A planetarium
- A scheduler
- A full astrophotography workflow manager

---

## Current Scope (MVP)

Astrolabe aims to provide:

- Camera capture
- Plate solving
- Mount connection and control
- Closed-loop goto (plate-solve centering)
- Polar alignment guidance
- Guiding via pulse corrections

---

## Target Environment

- Linux (Ubuntu/Debian primary target)
- SkyWatcher mounts (via INDI / EQMod initially)
- QHY cameras (via INDI initially)
- Local plate solving (ASTAP or astrometry.net)

Support for additional hardware depends on backend compatibility.

---

## Quickstart (Conceptual)

```bash
# Capture an image
astrolabe capture --exposure 2.0

# Plate solve last image
astrolabe solve

# Connect to mount
astrolabe mount connect

# Slew to coordinates
astrolabe mount slew --ra 10:45:03 --dec -59:41:04

# Center target using closed-loop solve
astrolabe goto "NGC 3372"

# Run polar alignment routine
astrolabe polar

# Start guiding
astrolabe guide start
