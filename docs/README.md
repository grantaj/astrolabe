# Documentation authority

Astrolabe deliberately keeps a small documentation surface. This file defines how to interpret it.

## Order of authority

When sources disagree, use this order:

1. **Current code and executable tests** define implemented behaviour.
2. **Living repository documentation** defines intended current contracts, invariants, and policy.
3. **Open GitHub issues** define planned future work.
4. **Git history and merged pull requests** preserve historical plans and rationale.

A historical plan is not a current instruction merely because it once lived in the repository.

## Living documents

- `../README.md` — current user-facing overview and setup.
- `../CONTRIBUTING.md` — development discipline and dependency policy.
- `vision.md` — product scope and non-goals.
- `architecture.md` — current high-level capability ownership and layering.
- `conventions.md` — coordinate, unit, time, and numerical invariants.
- `interfaces.md` — current logical component contracts and implemented service surfaces.
- `cli.md` — stable CLI/output contract and current command topology.
- `focus.md` — current focus-analysis behaviour.
- `live_camera.md` — current live-camera transport behaviour.

Focused component documents exist only when they describe current behaviour that would be awkward or noisy in the core documents.

## Planning policy

Do not add implementation plans, roadmaps, status snapshots, or completed-plan archives under `docs/`.

Future work belongs in GitHub issues, where dependencies, acceptance criteria, discussion, and lifecycle state can remain visible. Once work is implemented, the issue/PR and git history provide the historical record; update the living docs only where the implemented contract or policy changed.

This rule is intentional: fewer plausible sources of truth means less drift and less chance that an agent implements an obsolete design.
