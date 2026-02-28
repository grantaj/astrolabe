# Integration Test Container Plan

Goal: create a self-contained Docker image that runs the full integration test suite for the INDI mount backend and ASTAP solver backend, including all system dependencies, star databases, and an entrypoint that orchestrates `indiserver` startup before executing `pytest --integration`.

Date: 2026-02-22

---

## 1. Target integration tests

| Test | File | System dependencies | Data dependencies |
|---|---|---|---|
| `test_indi_mount_slew_and_state` | `tests/mount/test_indi_mount.py` | `indiserver`, `indi_simulator_telescope`, `indi_getprop`, `indi_setprop` | None |
| `test_indi_mount_connect_and_state` | `tests/mount/test_indi_mount.py` | Same as above | None |
| `test_astap_solve_integration_synthetic` | `tests/solver/test_astap.py` | `astap_cli`, `indiserver`, `indi_simulator_ccd` | D05 star database, Tycho-2 catalog → synthetic FITS |

---

## 2. Files to create

| File | Purpose |
|---|---|
| `Dockerfile` | Container image definition |
| `.dockerignore` | Exclude build artifacts from context |
| `scripts/integration-entrypoint.sh` | Entrypoint: starts INDI, runs tests |

The following existing files are modified: `scripts/install-tycho2.sh`, `astrolabe/mount/indi.py`, and `astrolabe/indi/client.py`.

---

## 3. `.dockerignore`

Excludes `.venv/`, `__pycache__/`, `*.pyc`, `*.pyo`, `.git/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `testdata/raw/`, `tycho2/`, `hyg4.2/`, `build/`, `dist/`, `*.egg-info/`, `docs/dev/reviews/`.

Rationale: Tycho-2 data is downloaded inside the container. Excluding `.git` and `.venv` prevents multi-MB waste in the build context.

---

## 4. Dockerfile

Base image: `ubuntu:24.04` (Noble — matches the INDI PPA `Suites: noble`).

### Layer structure (top to bottom)

1. **System packages + INDI PPA**
   - First `RUN`: install `ca-certificates` (needed for PPA HTTPS).
   - Write the INDI PPA `.sources` file with embedded GPG key to `/etc/apt/sources.list.d/indi.sources`.
   - Second `RUN`: install `curl`, `indi-bin`, `libindi1`, `unzip`. INDI is version-pinned via a build `ARG` (e.g. `INDI_VERSION=2.1.9+…`). Python is managed by `uv` (see layer 5).

2. **ASTAP CLI** (SHA-256 pinned)
   - Download `.zip` from SourceForge (`astap_cli_amd64.zip`).
   - Verify SHA-256 checksum, extract with `unzip -d /usr/bin/`.

3. **ASTAP D05 star database**
   - Download D05 `.deb` from SourceForge.
   - Install with `dpkg -i`.
   - Set `ASTAP_DB` env var to installed path.

4. **Tycho-2 catalog**
   - Copy and run `scripts/install-tycho2.sh` (~120 MB download from CDS Strasbourg).
   - Installed at `/opt/astrolabe/tycho2/`.

5. **Python environment**
   - Install `uv` via its official installer script (downloaded from GitHub with SHA-256 checksum verification, pinned to a specific release). Set `PATH` to include `/root/.local/bin` so `uv` is available in subsequent layers.
   - Copy `pyproject.toml` + `uv.lock` first (layer caching).
   - Run `uv venv --python 3.11 .venv && uv sync --extra dev --extra tools`.

6. **Application code**
   - `WORKDIR /opt/astrolabe` (set earlier, before Tycho-2 install)
   - `COPY . .`

7. **Environment variables**
   - `ASTAP_DB=/opt/astap` is set immediately after the D05 database install (layer 3) so it is available during subsequent build steps.
   - The remaining variables are set after application code is copied:
   ```
   ASTROLABE_INDI_INTEGRATION=1
   ASTAP_CLI=astap_cli
   ```

8. **Entrypoint**
   - `ENTRYPOINT ["scripts/integration-entrypoint.sh"]`
   - `CMD ["--integration"]`

### Design decisions

- **Single stage:** all dependencies are runtime (INDI, ASTAP, Python), so multi-stage would not save image size.
- **Layer ordering:** system pkgs → ASTAP → database → Tycho-2 → Python deps → app code. Maximises Docker layer cache reuse; the expensive download layers rarely change.
- **No `USER` switch:** INDI simulators and ASTAP run as root in a disposable CI container. No secrets involved.
- **Pinned versions:** INDI is version-pinned via a build `ARG`. ASTAP CLI `.zip` is SHA-256 pinned for reproducible builds (the SourceForge URL is not versioned). `uv` installer pinned by version and SHA-256 checksum.

---

## 5. `scripts/integration-entrypoint.sh`

1. Trap `EXIT` to kill `indiserver` on any exit.
2. Start `indiserver indi_simulator_telescope indi_simulator_ccd` in background. The CCD simulator is needed by solver integration tests that capture synthetic FITS frames.
3. Poll `indi_getprop -1 -t 1 "Telescope Simulator.CONNECTION.CONNECT"` until it returns `Off` (device exists but is not yet connected), with a 15 s timeout (30 iterations × 0.5 s).
4. `exec uv run pytest "$@"` — replaces the shell process with pytest. The `--integration` flag is supplied via `CMD` in the Dockerfile, so it appears in `$@` by default.

The solver test's `synthetic_fits_path` fixture handles FITS generation internally — it symlinks `tycho2/` from the repo root and runs `gen_catalog_starfield.py` in a temp directory. The entrypoint only needs to ensure `tycho2/` exists at `/opt/astrolabe/tycho2/`.

---

## 6. Usage

```bash
# Build
docker build -t astrolabe-integration .

# Run all integration tests
docker run --rm astrolabe-integration

# Run only mount tests
docker run --rm astrolabe-integration --integration tests/mount/test_indi_mount.py

# Run only solver tests
docker run --rm astrolabe-integration --integration tests/solver/test_astap.py

# Verbose output
docker run --rm astrolabe-integration --integration -v
```

---

## 7. Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| ASTAP SourceForge URL changes | Build fails | Pin exact URL with version. Add clear error message. |
| Tycho-2 CDS mirror slow/down | Build very slow or fails | `curl -C -` retries. Layer is cached after first build. |
| INDI PPA key rotation | `apt-get update` fails | GPG key embedded in `.sources` file; update Dockerfile when rotated. |
| Image size (~1–2 GB) | Slow CI pulls | Acceptable for self-contained integration. Data layers are cached. |
| `indiserver` startup race | Mount tests fail intermittently | Polling loop with timeout in entrypoint ensures readiness. |
