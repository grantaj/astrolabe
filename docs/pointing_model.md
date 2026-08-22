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

Pointing does not have an alignment or initialization phase. Each normal `PointingService.point_to()` operation follows the same cycle:

```text
apply model -> slew -> solve -> measure residual -> update model
```

The solved target residual is what remains **after** the current bias estimate has already been applied. The v1 model represents the underlying mount bias, so Pointing first reconstructs the corresponding bias observation:

```text
observed_bias = predicted_bias + post_correction_residual
```

It then passes that observation to `PointingModel.update()`, which applies a bounded exponential-style update independently to both bias components:

```text
b_new = (1 - weight) * b_old + weight * observed_bias
```

Equivalently for this offset model, `b_new = b_old + weight * residual`. Feeding the post-correction residual directly to the EMA would be wrong: under a stable mount bias it would make the estimate converge to only part of the true bias rather than cancelling the residual.

`weight` is clamped to `[0, 1]`; the current service weight is `0.1`.

The model is updated only when the solver reports success and supplies complete, finite, physically valid solved coordinates. Solver-specific ambiguity or failure belongs at the solver boundary and must be reported as an unsuccessful solve. Rejected observations do not change the model.

Mount sync is not part of this loop. Changing a mount's own coordinate mapping would create a second adaptive model and make the learned Astrolabe correction ambiguous, so ordinary pointing learns from the solved residual without syncing the mount.

## Persistence

`PointingModel` is pure prediction/update state, and `PointingService` receives a model explicitly. Ordinary model/service construction and updates do not implicitly read or write the filesystem.

Pointing-specific persistence is exposed separately through:

```text
default_model_path()
load_pointing_model(path)
save_pointing_model(model, path)
```

The application composition layer chooses when persistence happens and which path to use. The current CLI loads the model for a target-pointing operation and saves it only after `PointingService` accepts a residual for learning. The default path remains `~/.astrolabe/pointing.json`.

## Future model work

Richer sky-dependent models are intentionally not specified here. Investigation beyond the global offset baseline is tracked in GitHub issue #65 and should update this document only when a different model is actually adopted.
