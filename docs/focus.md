# Focus measurement

Astrolabe keeps focus analysis small and instrument-like: it measures stellar image sharpness and provides manual no-look guidance, but it does not try to become a general imaging workflow or autofocus system.

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

`focus monitor` provides audible guidance by default through the shared Linux/macOS audio sink. Use `--no-audio` to deliberately disable sound without acquiring audio resources. The focus layer deliberately does not claim a physical focuser direction because manual focusing supplies no focuser position. Instead it classifies fresh HFR history into four truthful states:

- `unknown` — there is not yet enough evidence for useful guidance; an alternating two-tone cue is played;
- `improving` — recent HFR is decreasing in the user's current motion; a repeating high tone is played;
- `worsening` — recent HFR is increasing in the user's current motion; a repeating low tone is played;
- `best-observed` — improvement followed by worsening has bracketed a local best in the observed temporal path, and HFR has returned stably near that bracketed best; a continuous middle tone is played.

The user can therefore turn the focuser steadily, continue while the high cue reports improvement, reverse after the low cue shows that the best region has been crossed, and settle where the continuous best-observed cue is recovered. Pausing during an improving run is not enough to produce the best-observed cue. The audio describes image-quality evidence only: high/low tones never mean clockwise/counter-clockwise, inward/outward, or any other physical focuser direction.

Invalid measurements silence audio immediately and clear focus guidance history. History is also discarded after a long gap so stale measurements cannot be presented as current guidance. A significantly better newly observed HFR invalidates an older bracket and must itself be bracketed before `best-observed` can be emitted. Startup/runtime audio failures are reported explicitly rather than silently continuing as though no-look feedback were active. Stop with Ctrl-C. `--frames N` is available for a bounded run.

The monitor also prints one concise line per frame with HFR, accepted-star count, scatter, and the current guidance state. Useful controls include `--min-stars`, `--detection-sigma`, and an optional explicit `--saturation-level`.

Global `--json` preserves Astrolabe's normal single-object JSON envelope for `focus measure`. The continuous `focus monitor` command is deliberately human-interactive and rejects `--json` with one structured error object rather than creating an NDJSON stream.

## Scope boundary

HFR is an image-quality metric, not a signed physical focus error. A raw HFR value therefore must not be sent to the generic signed manual-adjustment feedback service as though it told the user which direction to turn the focuser.

Focus guidance owns only the temporal inference justified by HFR history. The presentation layer maps those focus-specific states onto the shared backend-neutral `AudioCue`/`AudioSink` boundary. A future position-aware optimiser may combine focuser position with HFR history to infer a signed correction, but MVP manual focusing does not require focuser hardware or fabricate that information.

Live monitoring uses the camera-owned synchronous live-frame session. Focus remains independent of INDI details and platform audio implementation details.
