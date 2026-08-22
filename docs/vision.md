# Vision

Astrolabe is a minimal, instrument-like command-line tool for telescope operation and astrometric assistance.

It exists to make a small number of observing tasks precise, deterministic, scriptable, and understandable without becoming a general astrophotography platform.

## Purpose

Astrolabe's core direction includes:

- reliable local plate solving;
- deterministic mount control;
- solve-assisted pointing and centering;
- polar-alignment measurement and guidance;
- focused instrument utilities such as stellar focus measurement;
- an offline-first, observer-oriented target planner;
- stable guiding as a later capability.

Some of these capabilities are intentionally post-MVP or still incomplete. Current implementation status belongs in code/tests and `README.md`, not in this vision document.

## Design character

Astrolabe should remain:

- **CLI-first** — designed for terminal use and automation;
- **modular** — hardware/external implementations stay behind capability boundaries;
- **deterministic** — explicit outputs, stable automation contracts, bounded failure modes;
- **minimal** — no feature or abstraction without clear operational leverage;
- **testable** — core/domain behaviour can be exercised without physical hardware;
- **instrument-like** — precise and operationally legible rather than feature-rich.

## Non-goals

Astrolabe is not:

- a GUI application or planetarium;
- a full image acquisition/processing workflow suite;
- an observatory scheduler or automation platform;
- a general astronomy framework;
- a replacement for mature specialist tools when a clean backend boundary can use them instead.

Scope should be judged by whether a feature materially improves Astrolabe as a compact telescope/observing instrument, not by whether it can be made to fit a menu.

## MVP definition

The v0 usability target is:

1. connect to camera and mount;
2. capture and plate-solve an image;
3. slew and center a target via solve-based correction;
4. perform polar alignment with actionable guidance.

Guiding is explicitly **post-MVP**. It may be added after the first working release and must not become a release prerequisite through architecture or sequencing accident.

Implemented post-MVP capabilities do not redefine this baseline, and this document should not be used as a live status checklist.

## Long-term direction

Astrolabe may grow when additions preserve architectural clarity, keep dependencies justified, and leave generic/hardware/platform complexity at explicit boundaries.

The central design rule is:

> Time-dependent, hardware-specific, and platform-specific complexity belongs at explicit boundaries. Domain logic should remain clean, stable, and mathematically explicit.

For current architecture and dependency policy, see `architecture.md` and `../CONTRIBUTING.md`.
