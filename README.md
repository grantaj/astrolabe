# Astrolabe

Astrolabe is a minimal, Linux-first command-line instrument for telescope control and astrometric operations.

It is designed to be small, scriptable, deterministic, and reliable rather than a full imaging suite, planetarium, scheduler, or GUI application.

## What is on `main`

Current implemented capabilities include:

- INDI camera capture, including a bounded-overhead live-frame path;
- local plate solving through the solver backend abstraction (ASTAP by default);
- INDI mount status, slew, tracking, park, stop, sync, and pulse-guide primitives;
- offline target resolution;
- solve-assisted target pointing with continuous pointing-model learning;
- N-pose solve-based polar-axis measurement plus interactive one-axis-at-a-time AZ/ALT correction guidance with audible no-look feedback;
- multi-star HFR focus measurement and bounded live focus monitoring;
- an offline-first observing-target planner and catalog update tools.

Normal target pointing is one operation: apply the current error model, slew, solve the resulting position, measure the residual, and update the model from a trustworthy solve. There is no separate pointing initialization/alignment phase and Pointing does not sync the mount as part of learning. `pointing goto` is the canonical CLI command; `align goto` and top-level `goto` remain compatibility aliases. Use `mount slew` for a deliberately raw slew.

Polar adjustment now has real audio playback on Linux and macOS. Live focus monitoring still does not provide a truthful no-look focus guidance policy; that remaining focus-domain gap must be closed before manual focusing meets the v0 by-ear interaction target.

The guiding service is still a placeholder on current `main`; guiding commands report `not_implemented`. Guiding is post-MVP and does not block the first working release.

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

Interactive audio feedback uses a small system player rather than a Python multimedia dependency. On Linux, Astrolabe tries `pw-play`, `paplay`, then `aplay` and uses the first installed player that can open an output device; install the corresponding PipeWire, PulseAudio, or ALSA utility if none is available. On macOS, the built-in `afplay` utility is used. Audio is acquired only by interactive workflows that request it.

### Python environment

The repository uses `uv` for environment and dependency management:

```bash
uv sync --extra dev
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
