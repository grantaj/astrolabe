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

The mathematical analyser is backend-independent and accepts 2D numeric pixels. Camera/file conversion remains at the camera/imaging boundary. Focus measurement supports the existing on-disk FITS-path camera contract, in-memory NumPy arrays, and the in-memory `FitsImageData` produced by live camera sessions.

## CLI

Measure an existing FITS image:

```bash
astrolabe focus measure --in image.fits
```

Or capture one frame from the configured camera and measure it:

```bash
astrolabe focus measure --exposure 0.5 --bin 2 --roi 0,0,640,480
```

For manual focusing, consume the low-latency live camera path continuously:

```bash
astrolabe focus monitor --exposure 0.2 --bin 2 --roi 0,0,640,480
```

The monitor prints one concise line per frame with HFR, accepted-star count, scatter, and—once enough recent valid samples exist—a robust `improving`, `stable`, or `worsening` trend. Invalid frames are reported explicitly and reset the trend history so old measurements are not presented as current guidance. Stop with Ctrl-C. `--frames N` is available for a bounded run.

Useful controls include `--min-stars`, `--detection-sigma`, and an optional explicit `--saturation-level`.

Global `--json` preserves Astrolabe's normal single-object JSON envelope for `focus measure`. The continuous `focus monitor` command is deliberately human-interactive and rejects `--json` with one structured error object rather than creating an NDJSON stream.

## Scope boundary

HFR is an image-quality metric, not a signed physical focus error. A raw HFR value therefore must not be sent to the generic manual-adjustment feedback service as though it told the user which direction to turn the focuser.

The monitor's `improving` / `stable` / `worsening` label is descriptive only: it compares recent HFR measurements and does not imply a signed physical focuser correction. A future position-aware optimiser can combine focus position with HFR history to infer such a correction.

Live monitoring uses the camera-owned synchronous live-frame session from issue #40. Focus remains independent of INDI details and focuser hardware.
