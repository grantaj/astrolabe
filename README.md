# Astrolabe

Astrolabe is a minimal, Linux-first command-line instrument for telescope control and astrometric operations.

It is designed to be small, scriptable, deterministic, and reliable rather than a full imaging suite, planetarium, scheduler, or GUI application.

## What is on `main`

Current implemented capabilities include:

- INDI camera capture, including a bounded-overhead live-frame path;
- local plate solving through the solver backend abstraction (ASTAP by default);
- INDI mount status, slew, tracking, park, stop, sync, and pulse-guide primitives;
- offline target resolution;
- solve/sync/initial-alignment/pointing-aware goto operations;
- N-pose solve-based polar-axis measurement and mechanical correction estimates;
- multi-star HFR focus measurement;
- an offline-first observing-target planner and catalog update tools.

The closed-loop `GotoService` and guiding service are still placeholders on current `main`. The top-level `goto` command currently falls back to issuing a plain mount slew when closed-loop centering is unavailable; guiding commands report `not_implemented`.

For the exact command surface, use `astrolabe --help` and the relevant subcommand `--help`. `docs/cli.md` records the stable CLI contract without duplicating every parser flag.

## Design principles

Astrolabe is:

- **CLI-first** — intended for terminal use and automation;
- **modular** — camera, solver, mount, and service capabilities have explicit boundaries;
- **scriptable** — `--json` provides a stable single-object machine-readable envelope;
- **deterministic** — failures and exit states are explicit;
- **instrument-like** — precision and operational clarity matter more than feature count.

See `docs/README.md` for which repository documents are authoritative, `docs/vision.md` for scope, and `CONTRIBUTING.md` for development and dependency policy.

## Development setup

Astrolabe currently targets Linux, with Ubuntu/Debian as the primary environment.

### System dependencies

Install INDI using the packaging appropriate for your distribution. On Ubuntu, the official INDI PPA can be used:

```bash
sudo add-apt-repository ppa:mutlaqja/ppa
sudo apt update
sudo apt install indi-full
```

The CCD Simulator also uses GSC data when generating synthetic star fields:

```bash
sudo apt install gsc gsc-data
```

ASTAP is the default plate-solver backend. Install its Linux CLI and a suitable star database from the ASTAP project.

### Python environment

The repository uses `uv` for environment and dependency management:

```bash
uv sync --extra dev --extra tools
```

Run the CLI and tests through the managed environment:

```bash
uv run astrolabe --help
uv run pytest
```

The `tools` extra contains optional FITS/catalog tooling; normal runtime capabilities should not depend on it unless explicitly documented.

### Configuration and simulator smoke test

Copy the example configuration and adjust it for your devices:

```bash
mkdir -p ~/.config/astrolabe
cp astrolabe/config.toml ~/.config/astrolabe/config.toml
```

For the repository simulator setup:

```bash
bash scripts/setup_indi_simulators.sh
uv run astrolabe doctor
```

A typical capture/solve cycle is then:

```bash
uv run astrolabe capture --exposure 2.0 --out /tmp/frame.fits
uv run astrolabe solve /tmp/frame.fits
```

For integration-test details, use the repository test/CI entry points rather than old implementation plans; historical plans remain available in git and merged PR history.

## Documentation

The documentation lifecycle is deliberately small:

- current behaviour and contracts: `README.md`, `CONTRIBUTING.md`, and `docs/`;
- planned work: open GitHub issues;
- historical design/implementation rationale: git and merged pull requests.

Start at `docs/README.md`.
