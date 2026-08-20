# Architecture

Astrolabe is a small command-line instrument built from capabilities with narrow ownership boundaries. The objective is not architectural uniformity; it is to keep hardware/time-dependent complexity at explicit edges and keep domain logic testable.

For coordinate/unit invariants, see `conventions.md`. For dependency and internal-component policy, see `../CONTRIBUTING.md`.

## Capability map

```text
CLI / application composition
    |
    +--> camera --------> INDI transport
    +--> mount ---------> INDI transport + mount-owned frame transform
    +--> solver --------> external/in-process solver backend
    +--> target resolver
    +--> planner
    `--> services
          +--> pointing
          +--> polar
          +--> focus
          +--> feedback
          +--> goto      (placeholder on current main)
          `--> guiding   (placeholder on current main)

leaf utilities: util/*
```

The CLI/application layer is the composition root. It may know broadly about configuration and multiple capabilities in order to assemble them. Individual capabilities should not.

## Hard layering rules

### Hardware and external tools stay behind capability boundaries

Services must not import INDI or solver-specific implementations directly. Camera, mount, and solver backends translate between external representations and Astrolabe contracts.

The shared `astrolabe.indi` layer owns low-level INDI transport mechanics. Device semantics remain with camera or mount rather than moving into a generic INDI device framework.

### Mount frame conversion stays with the mount

Astrolabe's canonical celestial frame is ICRS/J2000-equivalent. A mount backend may need epoch-of-date/apparent coordinates. That time-dependent transformation remains mount-owned and must not leak into services.

A mount that natively accepts the canonical frame should avoid unnecessary transformation.

### Services own domain orchestration, not platform effects

Services combine capability contracts and domain mathematics. They must remain testable with fakes and should not own terminal rendering, platform audio, filesystem policy, or global configuration unless that side effect is intrinsically part of the capability.

### CLI stays thin

The CLI parses arguments, composes dependencies, invokes capabilities/services, renders human or JSON output, and maps failures to exit codes. Domain algorithms do not belong in the CLI.

### Utilities are leaves

`util/*` contains genuinely shared low-level primitives. It must not become a generic `core` dumping ground or import upward into application capabilities.

## Internal dependency principle

Only composition roots should know broadly about the application. Every substantial capability should otherwise behave like a good dependency: a small coherent public surface, narrow sibling dependencies, explicit side effects, and no accidental implementation leakage. Extractability is a design test, not a packaging goal.

The authoritative dependency/internal-component policy is in `CONTRIBUTING.md`; this document deliberately does not restate its full checklist.

## Current capability ownership

### Camera

Owns camera connection/capture and the synchronous live-frame session contract. One-shot capture remains appropriate for occasional solving; the live path exists for interactive consumers such as focus analysis. See `live_camera.md`.

### Solver

Owns `SolveRequest -> SolveResult` and backend-specific invocation/result translation. Services consume the solver contract and do not know whether the implementation is ASTAP or another backend.

### Mount

Owns primitive mount operations, mount-native INDI semantics, and coordinate-frame conversion at the mount boundary.

### Target resolution

Owns offline normalization and resolution of user/catalog target names into coordinates suitable for downstream operations.

### Pointing

Current `main` contains a pointing service plus a pointing-model package. The service provides solve/sync/initial-alignment/pointing-aware operations. Persistence ownership is known to need refinement and is tracked in GitHub issues; this document does not describe the proposed future structure as though already implemented.

### Polar alignment

Owns solve-based polar-axis measurement and correction geometry. Current measurement uses multiple solved poses and requires enough observations for a meaningful fit; algorithmic details belong in the implementation/tests rather than this high-level document.

### Focus

Owns backend-independent stellar sharpness analysis. HFR is an image-quality measurement, not a signed focuser correction. See `focus.md`.

### Feedback

Owns generic semantic/manual-adjustment feedback state. Platform rendering/audio belongs at presentation boundaries rather than in domain services.

### Planner

Owns offline-first target selection/scoring. It is intentionally separable from camera/mount control and remains post-MVP in product priority even though substantial functionality exists.

## Concurrency and ownership

Astrolabe is primarily synchronous. Interactive loops should use bounded, explicit ownership rather than application-wide async infrastructure.

Initial operational rule: one active session owns a hardware resource at a time. In particular, a live camera session is single-consumer and excludes ordinary capture until it is closed.

## Testing boundary

- pure/domain mathematics: deterministic unit tests;
- services: lightweight fake backends where practical;
- backend semantics: focused adapter tests;
- end-to-end external-tool/device behaviour: explicitly marked integration tests.

Architectural regressions include hardware imports in services, mount-frame conversion outside the mount boundary, broad application configuration leaking into capabilities, hidden side effects in ordinary domain APIs, or presentation policy leaking into domain services.
