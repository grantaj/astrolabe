# Integration Test Container Plan

Goal: create a self-contained Docker image that runs the full integration test suite for the INDI mount backend and ASTAP solver backend, including all system dependencies, star databases, and an entrypoint that orchestrates `indiserver` startup before executing `pytest --integration`.

Date: 2026-02-22

---

## 1. Target integration tests

| Test | File | System dependencies | Data dependencies |
|---|---|---|---|
| `test_indi_mount_slew_and_state` | `tests/mount/test_indi_mount.py` | `indiserver`, `indi_simulator_telescope`, `indi_getprop`, `indi_setprop` | None |
| `test_indi_mount_connect_and_state` | `tests/mount/test_indi_mount.py` | Same as above | None |
| `test_astap_solve_integration_synthetic` | `tests/solver/test_astap.py` | `astap_cli` | D50 star database, Tycho-2 catalog → synthetic FITS |

---

## 2. Files to create

| File | Purpose |
|---|---|
| `Dockerfile` | Container image definition |
| `.dockerignore` | Exclude build artifacts from context |
| `scripts/integration-entrypoint.sh` | Entrypoint: starts INDI, runs tests |

No existing files are modified.

---

## 3. `.dockerignore`

Excludes `.venv/`, `__pycache__/`, `.git/`, `.pytest_cache/`, `.ruff_cache/`, `testdata/raw/`, `tycho2/`, `hyg4.2/`, `build/`, `dist/`, `*.egg-info/`, `docs/dev/reviews/`.

Rationale: Tycho-2 data is downloaded inside the container. Excluding `.git` and `.venv` prevents multi-MB waste in the build context.

---

## 4. Dockerfile

Base image: `ubuntu:24.04` (Noble — matches the INDI PPA `Suites: noble`).

### Layer structure (top to bottom)

1. **System packages + INDI PPA**
   - Write the INDI PPA `.sources` file with embedded GPG key to `/etc/apt/sources.list.d/indi.sources`.
   - Install: `indi-bin`, `libindi-dev`, `libindi1`, `python3.11`, `python3.11-venv`, `python3-pip`, `wget`, `ca-certificates`.

2. **ASTAP CLI** (pinned version)
   - Download `.deb` from SourceForge (`astap_amd64.deb`).
   - Install with `dpkg -i` + `apt-get -f install -y`.
   - Verify: `astap_cli -h`.

3. **ASTAP D50 star database**
   - Download D50 `.deb` from SourceForge.
   - Install with `dpkg -i`.
   - Set `ASTAP_DB` env var to installed path.

4. **Tycho-2 catalog**
   - Copy and run `scripts/install-tycho2.sh` (~120 MB download from CDS Strasbourg).
   - Installed at `/opt/astrolabe/tycho2/`.

5. **Python environment**
   - Copy `pyproject.toml` + `uv.lock` first (layer caching).
   - Install `uv` via pip, run `uv sync --extra dev --extra tools`.

6. **Application code**
   - `COPY . /opt/astrolabe/`
   - `WORKDIR /opt/astrolabe`

7. **Environment variables**
   ```
   ASTROLABE_INDI_INTEGRATION=1
   ASTAP_CLI=astap_cli
   ASTAP_DB=/opt/astap
   ```

8. **Entrypoint**
   - `ENTRYPOINT ["scripts/integration-entrypoint.sh"]`
   - `CMD ["--integration"]`

### Design decisions

- **Single stage:** all dependencies are runtime (INDI, ASTAP, Python), so multi-stage would not save image size.
- **Layer ordering:** system pkgs → ASTAP → database → Tycho-2 → Python deps → app code. Maximises Docker layer cache reuse; the expensive download layers rarely change.
- **No `USER` switch:** INDI simulators and ASTAP run as root in a disposable CI container. No secrets involved.
- **Pinned versions:** ASTAP `.deb` pinned to a specific release for reproducible builds.

---

## 5. `scripts/integration-entrypoint.sh`

1. Start `indiserver indi_simulator_telescope` in background.
2. Poll `indi_getprop` until the simulator device appears (15 s timeout).
3. Run `uv run pytest --integration "$@"`.
4. Propagate pytest exit code.
5. Trap `EXIT` to kill `indiserver`.

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
| Tycho-2 CDS mirror slow/down | Build very slow or fails | `wget -c` retries. Layer is cached after first build. |
| INDI PPA key rotation | `apt-get update` fails | GPG key embedded in `.sources` file; update Dockerfile when rotated. |
| Image size (~1–2 GB) | Slow CI pulls | Acceptable for self-contained integration. Data layers are cached. |
| `indiserver` startup race | Mount tests fail intermittently | Polling loop with timeout in entrypoint ensures readiness. |
