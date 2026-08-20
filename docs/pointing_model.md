# Pointing model reference

This document records the **current implemented pointing model** and its geometry. It intentionally does not describe speculative richer models; those belong in GitHub issues.

For coordinate/unit conventions, see `conventions.md`.

## Current model

Astrolabe currently learns a two-component tangent-plane bias:

```text
b = (b_alpha, b_delta)
```

Both components are stored in radians.

The model state also records:

- schema version;
- number of samples incorporated;
- timestamp of the most recent update.

This is deliberately an **offset-only v1 model**. It is small, interpretable and easy to validate.

## Tangent-plane error convention

For a target `(ra_target, dec_target)` and a solved position `(ra_solved, dec_solved)`, Astrolabe first wraps the RA difference to `[-pi, pi)` and then computes:

```text
d_alpha = wrapped(ra_solved - ra_target) * cos(dec_target)
d_delta = dec_solved - dec_target
```

`d_alpha` and `d_delta` are therefore small local tangent-plane residuals rather than raw spherical coordinate differences.

## Applying the model

For a requested target, the predicted bias is subtracted before commanding the mount:

```text
ra_corrected  = normalize(ra_target - b_alpha / cos(dec_target))
dec_corrected = dec_target - b_delta
```

The corrected RA is normalized after applying the offset.

The small-angle representation is intended for ordinary pointing residuals, not arbitrary large separations or operations near the singularity at the celestial poles.

## Learning

`PointingModel.update()` currently applies a bounded exponential-style update independently to both bias components:

```text
b_new = (1 - weight) * b_old + weight * residual
```

`weight` is clamped to `[0, 1]`; the current service default is `0.1`.

The model should only be updated from a meaningful solved-target residual. A mount sync is different: sync changes the mount's own coordinate mapping, so the pre-sync discrepancy must not also be learned as a persistent Astrolabe correction.

## Persistence: current behaviour and ownership direction

On current `main`, the service/model path still loads and saves `~/.astrolabe/pointing.json` implicitly. This is current behaviour, but it is not the desired long-term ownership boundary.

GitHub issue #59 tracks separating pure model logic from persistence and making persistence explicit at the composition boundary. Until that lands, tests and callers should treat the current file behaviour as compatibility rather than as an architectural pattern to copy.

## Future model work

Richer sky-dependent models are intentionally not specified here. Investigation beyond the global offset baseline is tracked in GitHub issue #65 and should update this document only when a different model is actually adopted.
