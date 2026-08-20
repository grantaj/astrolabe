# Planner visibility reference

This document records the **current implemented visibility-scoring rationale**. It is explanatory reference material, not a roadmap. Calibration and possible behavioural changes are tracked in GitHub issues.

The planner uses visibility as one factor in a broader score; visibility is not a promise that an object will or will not be observable.

## Inputs

Visibility scoring currently uses, where available:

- target type;
- integrated magnitude;
- angular size / major and minor axes;
- catalog surface brightness;
- target altitude;
- SQM or Bortle class;
- telescope aperture.

Solar-system targets (`planet`, `moon`, `sun`) currently bypass this visibility penalty and receive visibility score `1.0`.

If neither SQM nor Bortle is available, the visibility component is neutral (`1.0`) rather than fabricating a sky condition.

## Sky brightness

SQM is the primary sky-brightness input. When only Bortle class is supplied, Astrolabe converts the class to an approximate representative SQM value.

The effective sky brightness is adjusted for altitude with a simple airmass approximation:

```text
X = 1 / sin(altitude)
mu_sky = SQM - 0.8 * (X - 1)
```

The implementation clamps altitude to the range 5–90 degrees for this calculation.

This is a ranking heuristic, not a detailed atmospheric model.

## Point-like targets

Stars, doubles, open clusters and sufficiently compact targets are treated as point-like rather than through mean surface-brightness contrast.

Astrolabe estimates a rough visual limiting magnitude:

```text
NELM   = SQM - 14
LM_tel = NELM + 5 * log10(aperture_mm) - 5
margin = LM_tel - target_mag
```

If aperture is not supplied, the current fallback is 80 mm.

A non-negative margin receives full visibility score. Negative margin decays smoothly as `exp(margin)`.

This path exists to rank point-source detectability sensibly; it must not be presented as a precise limiting-magnitude prediction for a real observer/system.

## Extended targets

Extended objects use contrast between effective object surface brightness and effective sky brightness.

If catalog surface brightness is available, Astrolabe uses it. Otherwise it estimates mean surface brightness from integrated magnitude and apparent elliptical area.

For ordinary extended objects the estimate is based on:

```text
mu_obj ~= mag + 2.5 * log10(area_arcsec2)
```

Nebulae currently use a reduced area coefficient (`1.5` rather than `2.5`) so large structured nebulae are not over-penalized purely by their full catalog extent.

The implementation then applies a simple structure adjustment:

- emission/reflection/nebula types: `-1.0 mag` effective boost;
- globular clusters: `-1.0 mag` effective boost;
- other extended targets: no structure boost.

The resulting contrast difference is:

```text
delta_mu = mu_obj - mu_sky
```

Objects at least as bright per unit area as the effective sky (`delta_mu <= 0`) receive full visibility score. Positive `delta_mu` decays as:

```text
exp(-1.2 * delta_mu)
```

## Why the model is split

Mean surface brightness is useful for diffuse galaxies/nebulae but is the wrong primary model for star fields and compact point sources. Conversely, integrated magnitude alone can make a very large diffuse object look easier than it really is.

The current split is therefore deliberate:

- point-like targets -> limiting-magnitude margin;
- extended targets -> surface-brightness contrast;
- structured objects -> small class-specific corrections to the extended model.

The goal is an explainable, monotonic ranking heuristic that behaves more like practical observing than a single integrated-magnitude score.

## Calibration status

The constants above are implementation choices, not physical constants. Focused regression coverage and calibration work are tracked in GitHub issue #64. Any future behavioural change should update tests and this document together.

Camera-derived current-condition inputs such as transparency/seeing are future work tracked separately in GitHub issue #63; they are not part of the current visibility implementation described here.
