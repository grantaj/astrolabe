# Contributing

Astrolabe is designed to remain small, precise, and architecturally
clean.

Contributions are welcome, but must preserve the project's core
invariants and philosophy.

------------------------------------------------------------------------

## 1. Architectural Discipline

Before submitting changes, review:

-   `docs/conventions.md`
-   `docs/architecture.md`
-   `docs/interfaces.md`
-   `docs/cli.md`

The following rules are strict:

-   Core logic must not depend directly on hardware libraries.
-   All internal angles must use radians.
-   Internal coordinate frame is ICRS/J2000.
-   Mount frame conversions occur only inside mount backends.
-   CLI remains thin and stable.

If your change violates one of these, it requires explicit discussion.

------------------------------------------------------------------------

## 2. Scope Control

Astrolabe is intentionally minimal.

Features that do NOT belong:

-   GUI components
-   Planetarium features
-   Imaging workflow management
-   Observatory scheduling
-   Large dependency additions without strong justification

If a feature does not improve solving, pointing, polar alignment, or
guiding, it likely does not belong.

------------------------------------------------------------------------

## 3. CLI Stability

The CLI is a public contract.

-   Command names are stable once released.
-   JSON output fields are stable once released.
-   Breaking changes require a major version bump.

Additive changes are preferred over breaking changes.

------------------------------------------------------------------------

## 4. Code Style Guidelines

-   Keep modules small and focused.
-   Avoid circular dependencies.
-   Prefer explicit math over implicit behavior.
-   Fail clearly and explicitly.
-   Do not print directly from backend modules.

------------------------------------------------------------------------

## 5. Dependencies

Astrolabe minimises **total complexity, not dependency count**.

-   Keep the mandatory dependency surface small. A core dependency must
    support pervasive instrument functionality and earn its installation
    and maintenance cost.
-   Keep specialised capabilities optional and behind Astrolabe interfaces
    where practical.
-   Prefer a mature, well-maintained library over reimplementing a
    substantial body of established specialist functionality merely to
    remain dependency-free.
-   Keep small, stable, domain-specific algorithms and mathematical
    primitives in Astrolabe when they are clearer to own than to outsource.
-   Do not add abstraction layers whose only purpose is to hide a
    dependency.

The same discipline applies **inside Astrolabe**. Treat each substantial
capability as if it were an external dependency:

-   Give it a small, coherent public surface and depend on sibling public
    contracts rather than their implementation details.
-   Keep its dependency surface no broader than its responsibility requires;
    avoid cycles and accidental sideways ownership.
-   Keep configuration, filesystem, presentation, and hardware side effects
    at explicit boundaries. Only composition roots should know broadly about
    the application.
-   Use extractability as a design test: a well-factored capability should be
    movable without redesigning its interface. This is a heuristic, not a
    goal to create separate packages.
-   Do not add interfaces, wrappers, service containers, or packaging splits
    merely to satisfy architectural purity.

In short: **minimal dependency surface; no dependency without leverage;
no reimplementation for purity. Every substantial capability should behave
like a good dependency.**

------------------------------------------------------------------------

## 6. Testing Expectations

-   Core math should be unit-testable without hardware.
-   Hardware-specific behavior should be isolated behind backends.
-   Deterministic behavior is preferred wherever possible.

------------------------------------------------------------------------

## 7. Philosophy

Astrolabe aims to remain:

-   Instrument-like
-   Predictable
-   Scriptable
-   Architecturally coherent

Precision over feature count.

If in doubt, simplify.
