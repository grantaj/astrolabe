# Live camera frames

Astrolabe's ordinary `CameraBackend.capture()` path is intentionally simple and
remains the right interface for occasional plate-solving captures. Interactive
services such as focusing need a different transport property: a sequence of
fresh complete frames without a process-per-poll and file-path rendezvous on
every exposure.

## Camera contract

Camera backends may implement:

```python
with camera.live_frames(
    exposure_s=0.1,
    gain=None,
    binning=2,
    roi=(0, 0, 320, 240),
    frame_count=None,
) as frames:
    for image in frames:
        ...
```

`LiveFrameSession` is synchronous and single-consumer. Requesting the next item
starts the next exposure and waits for one complete frame. This deliberately
provides backpressure rather than introducing a background producer, queue,
event bus, or observatory job system. A camera backend permits only one active
live session at a time, and ordinary one-shot capture is rejected while that
session owns the camera.

`frame_count` is optional. A bounded session closes itself after the requested
number of frames; an unbounded session is normally used inside a context manager
and stopped by the caller (for example on `Ctrl-C`). Closing a session releases
its transport and restores the camera's previous INDI upload mode.

## Frame representation

The INDI live path yields the existing `solver.types.Image` object. Unlike the
legacy INDI one-shot path, which stores an on-disk FITS path in `Image.data`, the
live path stores `FitsImageData`: an explicit wrapper around uncompressed FITS
bytes received in memory.

Each live `Image` includes:

- non-zero `width_px` and `height_px` read from the FITS header;
- the INDI BLOB timestamp when valid, normalized to UTC;
- the requested exposure time;
- `metadata["transport"] == "indi_blob"`;
- the BLOB property/format and a one-based frame sequence number.

Keeping the payload explicit avoids adding another ad-hoc meaning to
`Image.data`. Image-analysis services can decode `FitsImageData` at the camera /
imaging boundary without importing or understanding INDI.

## INDI transport

The portable live path uses repeated still exposures and standard INDI BLOB
delivery. Astrolabe opens one narrow persistent INDI XML connection scoped to
the configured camera's `CCD1` BLOB (`CCD2` for the guider head), enables BLOB
mode, and sends exposure requests on that same connection.

The live hot path therefore does **not**:

- poll `CCD_FILE_PATH`;
- launch `indi_getprop` once per frame;
- depend on `UPLOAD_LOCAL`;
- accumulate capture files;
- require `CCD_VIDEO_STREAM`.

Only `.fits` and zlib-compressed `.fits.z` BLOBs are accepted. Unsupported BLOB
formats are reported as `BackendError` rather than guessed. Because a new
exposure is not requested until the consumer asks for the next item, normal
still-image operation cannot build an unbounded queue. If multiple matching BLOB
updates are already present in one received batch, only the latest complete
frame is retained.

The ordinary `capture()` implementation is unchanged in purpose and continues
to use the existing local-file path for solve-oriented work.

## Benchmarking

The simulator benchmark compares the existing one-shot path with the persistent
BLOB path using the same exposure, binning, and ROI:

```bash
scripts/integration-entrypoint.sh --integration \
  tests/camera/test_indi_live_integration.py -s

python scripts/benchmark_camera_live.py \
  --device "CCD Simulator" --frames 25 --exposure 0.01 \
  --binning 2 --roi 0 0 320 240 --polling-ms 25
```

The INDI CCD Simulator completes exposures from its polling timer. Its standard
`POLLING_PERIOD.PERIOD_MS` defaults to 1000 ms, which makes a 10 ms exposure
appear to take roughly one second regardless of transport. The benchmark fixture
therefore sets the simulator polling period to 25 ms before measuring either the
legacy or live path. This is deliberately test-only setup; Astrolabe never
changes the polling period of a user's camera.

The integration test first measures 20 sequential legacy `capture()` calls,
then runs 100 sequential live frames with the same 10 ms exposure and focus-sized
ROI. It reports both medians and their speedup, verifies that no live capture
files accumulate, and enforces a steady-state live non-exposure overhead of at
most 250 ms on the localhost CCD Simulator. CI runs this bounded simulator test
in addition to the normal hardware-free unit suite.
