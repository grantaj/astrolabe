# Focus measurement

Astrolabe keeps focus analysis small and instrument-like: it measures stellar image sharpness, but it does not try to become a general imaging workflow.

## Measurement

The focus analyser uses empirical multi-star **half-flux radius (HFR)**. Lower HFR means sharper stars.

For each monochrome frame it:

1. estimates the background and noise robustly;
2. finds compact local stellar peaks;
3. rejects unsuitable candidates such as edge-truncated, saturated, hot-pixel-like, blended/duplicate, or strongly elongated detections;
4. computes a local background, flux-weighted centroid, and half-flux radius for each accepted star;
5. reports the median HFR across accepted stars together with the HFR median absolute deviation and accepted/rejected star counts.

An unusable frame is an explicit invalid measurement. Astrolabe does not reuse a stale HFR or invent a value when too few stars are usable.

The mathematical analyser is backend-independent and accepts 2D numeric pixels. Camera/file conversion remains at the camera/imaging boundary. The current INDI camera backend returns a FITS path in `Image.data`; focus measurement supports that existing contract as well as in-memory NumPy arrays.

## CLI

Measure an existing FITS image:

```bash
astrolabe focus measure --in image.fits
```

Or capture one frame from the configured camera and measure it:

```bash
astrolabe focus measure --exposure 0.5 --bin 2 --roi 0,0,640,480
```

Useful controls include `--min-stars`, `--detection-sigma`, and an optional explicit `--saturation-level`. Global `--json` preserves Astrolabe's normal single-object JSON envelope; an invalid star field is a recoverable failure with the measurement details included.

## Scope boundary

HFR is an image-quality metric, not a signed physical focus error. A raw HFR value therefore must not be sent to the generic manual-adjustment feedback service as though it told the user which direction to turn the focuser.

A future position-aware optimiser can combine focus position with HFR history to infer a signed correction. Likewise, continuous low-latency focus monitoring depends on the live-frame camera capability tracked separately in issue #40. The focus analyser itself remains independent of either transport or focuser hardware.
