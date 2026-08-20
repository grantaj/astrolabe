# Contributing

Astrolabe is designed to remain small, precise, and architecturally clean. Contributions are welcome, but must preserve the project's core invariants and philosophy.

Before changing architecture or public behaviour, read `docs/README.md` to understand which repository documents are authoritative.

## 1. Architectural discipline

The living architecture documents are:

- `docs/vision.md` — product scope and non-goals;
- `docs/architecture.md` — capability ownership and layering;
- `docs/conventions.md` — units, frames, time, and numerical invariants;
- `docs/interfaces.md` — current logical interfaces;
- `docs/cli.md` — CLI/output contract.

The following rules are strict:

- Core/domain logic must not depend directly on hardware libraries.
- All internal angles use radians unless a boundary explicitly documents otherwise.
- Internal celestial coordinates use ICRS/J2000-equivalent semantics.
- Mount-native frame conversion occurs only inside the mount capability.
- CLI remains thin and stable.

If a change violates one of these, it requires explicit architectural discussion.

## 2. Scope control

Astrolabe is intentionally minimal.

Features that do not belong include:

- GUI/planetarium functionality;
- general imaging workflow management;
- observatory scheduling/automation;
- broad frameworks added for hypothetical future flexibility;
- large dependency additions without corresponding leverage.

A feature should materially improve Astrolabe as a compact telescope/observing instrument. If its value is primarily that Astrolabe *could* do it, it probably does not belong.

## 3. CLI stability

The CLI is a public contract.

- Command names and primary flags are stable once relied upon.
- JSON output fields are stable once relied upon.
- Breaking changes require deliberate versioning/migration consideration.
- Additive changes are preferred over breaking changes.

`docs/cli.md` records the contract; executable `--help` reflects the exact current parser surface.

## 4. Code style

- Keep modules small and focused.
- Avoid circular dependencies.
- Prefer explicit math over implicit behaviour.
- Fail clearly and explicitly.
- Do not print directly from backend/domain modules.
- Prefer moving responsibility to its natural owner over wrapping it in another abstraction.

## 5. Dependencies

Astrolabe minimises **total complexity, not dependency count**.

- Keep the mandatory dependency surface small. A core dependency must support pervasive instrument functionality and earn its installation and maintenance cost.
- Keep specialised capabilities optional and behind Astrolabe interfaces where practical.
- Prefer a mature, well-maintained library over reimplementing a substantial body of established specialist functionality merely to remain dependency-free.
- Keep small, stable, domain-specific algorithms and mathematical primitives in Astrolabe when they are clearer to own than to outsource.
- Do not add abstraction layers whose only purpose is to hide a dependency.

The same discipline applies **inside Astrolabe**. Treat each substantial capability as if it were an external dependency:

- Give it a small, coherent public surface and depend on sibling public contracts rather than their implementation details.
- Keep its dependency surface no broader than its responsibility requires; avoid cycles and accidental sideways ownership.
- Keep configuration, filesystem, presentation, and hardware side effects at explicit boundaries. Only composition roots should know broadly about the application.
- Use extractability as a design test: a well-factored capability should be movable without redesigning its interface. This is a heuristic, not a goal to create separate packages.
- Do not add interfaces, wrappers, service containers, or packaging splits merely to satisfy architectural purity.

In short: **minimal dependency surface; no dependency without leverage; no reimplementation for purity. Every substantial capability should behave like a good dependency.**

## 6. Testing expectations

- Core math should be unit-testable without hardware.
- Hardware-specific behaviour should be isolated behind backends.
- Deterministic behaviour is preferred wherever possible.
- Integration tests should be explicit about external tools/data/hardware requirements.

## 7. Documentation lifecycle

Do not add implementation plans, status snapshots, or completed-plan archives under `docs/`.

- Current contracts/policy belong in the living docs.
- Future implementation work belongs in GitHub issues.
- Historical implementation rationale belongs in git and merged PR history.

When a change lands, update only the living document whose contract/policy actually changed. Avoid copying the same rule into multiple files.

## 8. Philosophy

Astrolabe aims to remain instrument-like, predictable, scriptable, and architecturally coherent.

Precision over feature count. If in doubt, simplify.
