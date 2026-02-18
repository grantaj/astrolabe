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

# Plate solve a specific image
astrolabe solve testdata/raw/sample1.fits

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

## Development Setup (Ubuntu)

Astrolabe currently targets Linux (Ubuntu/Debian).

------------------------------------------------------------------------

### 1. System Dependencies

#### Install INDI

Add the official INDI PPA:

    sudo add-apt-repository ppa:mutlaqja/ppa
    sudo apt update

Install INDI:

    sudo apt install indi-full

Verify installation:

    indiserver --version

Install GSC (needed for CCD Simulator star fields):

    sudo apt install gsc gsc-data

------------------------------------------------------------------------

#### Install ASTAP

Download the Linux `.deb` package from:

https://www.hnsky.org/astap.htm

Then install it:

    sudo apt install ./astap_*.deb

Verify installation:

    astap -h

------------------------------------------------------------------------

### 2. Python Environment

From the repository root:

    python -m venv .venv --prompt astrolabe
    source .venv/bin/activate
    uv sync --extra dev --extra tools

Optional tools (FITS inspection and synthetic starfield generation) are included in the command above.

This uses `uv.lock` as the source of truth for reproducible installs. CI enforces this with `uv sync --frozen`.

------------------------------------------------------------------------

### 2.1. Lint and Format

    uv run ruff check .
    uv run ruff format .

------------------------------------------------------------------------

### 2.2. Tests

    uv run pytest

Note: the test configuration enables the `--ty` plugin. If you remove `pytest-ty`, also remove `--ty` from pytest options in `pyproject.toml`.

------------------------------------------------------------------------

### 2.3. Pre-commit Hooks

    uv run pre-commit install
    uv run pre-commit run --all-files

------------------------------------------------------------------------

### 3. Install Tycho-2 (for synthetic test data)

The synthetic starfield generator `scripts/gen_catalog_starfield.py` uses the Tycho-2 catalog.
To install it locally into `tycho2/`:

    bash scripts/install-tycho2.sh

This is required for the integration test that generates synthetic FITS files.

------------------------------------------------------------------------

### 4. Test Installation

Copy astrolabe/config.toml to ~/.config/astrolabe/config.toml

Start INDI simulator server and configure telescope + CCD settings:

    bash scripts/setup_indi_simulators.sh

In another terminal, capture a frame:

    astrolabe capture --exposure 2.0

Then run diagnostics:

    astrolabe doctor

Expected results:

-   config: OK
-   indi_server: OK
-   solver_astap: OK

---

### QHY Camera Testing

To test with a QHY camera (hardware or INDI driver), start the QHY INDI server in a separate terminal:

    indiserver indi_qhy_ccd

This allows Astrolabe to connect to the QHY camera via INDI for capture and plate solving. No changes to the simulator setup script are required.
