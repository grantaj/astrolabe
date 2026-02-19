# Vision

Astrolabe is a minimal, instrument-like command-line tool for telescope
control and astrometric operations.

It is designed to do a small number of critical tasks well, with
precision and clarity.

------------------------------------------------------------------------

## 1. Purpose

Astrolabe exists to provide:

-   Reliable plate solving
-   Deterministic mount control
-   Closed-loop goto centering
-   Clear polar alignment guidance
-   Stable guiding
-   A curated, observer-oriented target planner (post-MVP)

It prioritizes correctness, composability, and scriptability over
feature breadth.

------------------------------------------------------------------------

## 2. Design Principles

Astrolabe should be:

-   **CLI-first** -- designed for terminal use and automation
-   **Modular** -- hardware backends are swappable
-   **Deterministic** -- explicit outputs and stable JSON contracts
-   **Minimal** -- avoid feature creep and unnecessary abstractions
-   **Testable** -- core logic independent of hardware

------------------------------------------------------------------------

## 3. Non-Goals

Astrolabe is not:

-   A planetarium
-   A GUI application
-   A full astrophotography workflow suite
-   A scheduler or observatory automation system
-   A replacement for large ecosystem tools

If a feature does not directly improve solving, pointing, polar
alignment, or guiding, it likely does not belong in Astrolabe.

------------------------------------------------------------------------

## 4. MVP Definition (v0)

Astrolabe v0 is considered usable when a user can:

1.  Connect to camera and mount
2.  Capture and plate-solve an image
3.  Slew and center a target via closed-loop correction
4.  Perform polar alignment with actionable guidance
5.  Guide stably for at least 10 minutes

Anything beyond this is post-MVP.

------------------------------------------------------------------------

## 5. Long-Term Direction

Astrolabe may grow carefully in the future, but only if additions:

-   Preserve architectural clarity
-   Maintain small dependency surface
-   Do not introduce GUI complexity
-   Do not entangle core logic with hardware specifics

The project should remain focused and instrument-like --- more precision
tool than feature platform.

------------------------------------------------------------------------

## 6. Philosophy

Astrolabe follows a simple rule:

> Time-dependent or hardware-specific complexity belongs at the
> boundary.\
> Core logic should remain clean, stable, and mathematically explicit.

This document serves as a guardrail against scope drift and
architectural erosion.
