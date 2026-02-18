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

New dependencies should be:

-   Lightweight
-   Well-maintained
-   Justified by clear benefit

Avoid pulling in large frameworks.

------------------------------------------------------------------------

## 6. Testing Expectations

-   Core math should be unit-testable without hardware.
-   Hardware-specific behavior should be isolated behind backends.
-   Deterministic behavior is preferred wherever possible.
-   Use `uv sync --extra dev --extra tools` for local setup, and `uv run` for tools like `pytest` and `ruff`.
-   Install hooks with `uv run pre-commit install`, and run manually with `uv run pre-commit run --all-files`.

------------------------------------------------------------------------

## 7. Philosophy

Astrolabe aims to remain:

-   Instrument-like
-   Predictable
-   Scriptable
-   Architecturally coherent

Precision over feature count.

If in doubt, simplify.
