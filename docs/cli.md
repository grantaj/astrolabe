# CLI contract

Astrolabe's CLI is a stable automation boundary. This document records the contract and current command topology without duplicating every argparse option.

For exhaustive flags and defaults, the executable parser is authoritative:

```bash
astrolabe --help
astrolabe <command> --help
astrolabe <command> <subcommand> --help
```

## Global form

```text
astrolabe [global options] <command> [<subcommand>] [options]
```

Global options currently include `--config`, `--json`, `--log-level`, `--timeout`, `--dry-run`, and `--version`.

`--dry-run` is best-effort and command-specific; code/tests define whether a particular operation currently honours it. Never infer safety solely from the presence of the global flag.

## Exit codes

- `0` — success;
- `1` — recoverable operational failure;
- `2` — fatal/configuration/usage/internal failure where the command maps it as such.

Commands that expose not-yet-implemented services report a structured `not_implemented` failure rather than pretending to succeed.

## JSON output

The stable contract for global `--json` is one JSON object on stdout, with logs and diagnostics confined to stderr.

The envelope contains:

```text
ok             bool
timestamp_utc  ISO-8601 UTC timestamp
command        operation identifier
data           object or null
error          object or null
```

When present, `error` contains a stable reason `code`, human-readable `message`, and optional `details`.

Most current command result/error paths use this envelope through the shared CLI output/runtime machinery. A small set of legacy early-validation or command-specific failures still violate the contract by emitting bare stderr with no JSON object; fixing those implementation gaps is tracked in GitHub issue #72. They are defects against this contract, not a second supported output mode.

Do not introduce NDJSON/streaming output under the global `--json` flag without deliberately changing this contract.

## Current command topology

The topology below reflects the current implementation. Use `--help` for exact arguments.

| Command | Subcommands / purpose | Current status |
| --- | --- | --- |
| `doctor` | local configuration/backend diagnostics | implemented |
| `capture` | capture one camera frame | implemented |
| `solve` | plate-solve a FITS image | implemented |
| `view` | inspect a FITS file; optional graphical display | implemented |
| `mount` | `status`, `slew`, `track`, `park`, `stop` | implemented |
| `resolve` | resolve target names/catalog IDs offline | implemented |
| `goto` | deprecated alias for `pointing goto` | compatibility alias |
| `pointing` | `solve`, `goto` | implemented |
| `align` | deprecated alias for `pointing` | compatibility alias |
| `polar` | optional `measure` (default) or interactive `adjust` | implemented |
| `focus` | `measure` one-shot multi-star HFR; `monitor` live HFR plus no-look audio guidance | implemented |
| `guide` | `calibrate`, `start`, `stop`, `status` | CLI present; service placeholder |
| `plan` | offline-first target planning | implemented |
| `update catalog` | all/default catalog updates; `openngc`, `hip`, `bsc` subsets | implemented |

### Pointing command semantics

`pointing goto` is the single normal target-pointing operation. It applies the current persisted pointing model, slews, plate-solves the resulting position, measures the target residual, and incorporates the first trustworthy ordinary pointing observation into the model. If that solve is not yet within the visual-acquisition tolerance, the same operation makes bounded corrective slews and solves again. Corrective solves are used only to center the current target; they are not additional pointing-model samples.

Success means a trustworthy solve has confirmed the target within 300 arcsec (5 arcmin). The MVP centering policy allows at most three corrective slews, 120 seconds of centering time, and a 5-degree single correction. Repeated solve failure, clear stagnation, unsafe correction geometry, or mount/backend failure ends the operation without claiming the target is centered.

The 10-degree pointing-model learning envelope is separate from the 5-arcmin acquisition tolerance: it is a corruption guard for deciding whether an ordinary solved pointing is trustworthy enough to learn from, not a definition of pointing success.

`align goto` and top-level `goto` are compatibility spellings for the same Pointing operation. They retain their own command identifiers for automation compatibility but do not own different domain behavior. Old top-level `goto` tolerance/iteration flags remain accepted but hidden as compatibility no-ops; they do not override the canonical bounded-centering policy.

Use `mount slew` when the desired operation is deliberately just an uncorrected mount slew rather than solve-assisted pointing, learning, and centering.

### Polar command semantics

`polar` with no action and `polar measure` both perform the established N-pose measurement and return the same `PolarResult`/JSON shape. The RA rotation remains required; observer latitude may be supplied explicitly or taken from the configured mount/site location.

`polar adjust` first performs that same measurement once, then disables tracking and guides manual azimuth and altitude adjustment sequentially. Azimuth is always completed and stably confirmed before altitude is rebased and activated. Human guidance uses physical directions: AZ `east`/`west`, ALT `raise`/`lower`. Tracking is restored on completion, failure, or Ctrl-C.

Audible feedback is enabled by default for `polar adjust` and is driven from the same semantic feedback updates as the terminal presentation. Astrolabe opens one persistent `miniaudio` playback device for the interactive session and streams generated cue samples through it; stable cues therefore remain continuous without restarting file-player processes. Linux uses miniaudio's PulseAudio/ALSA/JACK backends, while macOS uses CoreAudio. If no supported audio backend or default output device can be opened, the command fails rather than claiming that no-look feedback is active. `--no-audio` deliberately disables sound and avoids acquiring audio resources.

The adjustment loop emits a stream of human feedback, so global `--json` is deliberately rejected with one structured `interactive_json_unsupported` error rather than inventing an NDJSON protocol. The final one-shot `polar`/`polar measure` path remains JSON-compatible.

### Focus command semantics

`focus measure` remains a one-shot HFR measurement. `focus monitor` consumes the camera-owned live-frame stream and provides no-look manual-focus feedback by default through the same shared `AudioSink` used by polar adjustment. `--no-audio` deliberately disables sound and avoids acquiring the sink.

Focus has no focuser-position input, so its audio deliberately does not encode a signed physical correction. Fresh HFR history is classified as `unknown`, `improving`, `best-observed`, or `worsening`. An alternating two-tone cue means unknown, a repeating high tone means HFR is improving in the user's current motion, and a repeating low tone means HFR is worsening. The continuous middle tone is reserved for a bracketed best region: improvement followed by worsening must first demonstrate that a local best has been crossed, then HFR must return stably near that best. A pause during an improving run is therefore not presented as best focus, and a substantially better newly observed HFR requires a fresh bracket.

This makes manual focusing usable by ear without claiming clockwise/counter-clockwise or inward/outward focuser direction that Astrolabe cannot know. Invalid measurements silence audio and reset the guidance history; stale history is discarded before new guidance is emitted. If the shared audio backend cannot start or fails at runtime, `focus monitor` reports the failure rather than silently continuing as though no-look guidance were active.

`focus monitor` remains a human-interactive stream and rejects global `--json` with one structured error rather than inventing NDJSON. `--frames N` bounds the run when needed.

### A few non-obvious current boundaries

- `view` takes its FITS input via `--in` on current main; its `header` field is the primary header in file order, decoded by Astrolabe's own narrow FITS boundary — see `fits_boundary.md`.
- `polar` requires an RA rotation. `polar adjust` additionally requires longitude; latitude/longitude/elevation can come from CLI overrides or configured mount/site location. Exposure/settling and pose-count controls remain shared with measurement. `--no-audio` is specific to the interactive adjustment path; measurement does not acquire audio.
- `focus measure` accepts either `--in` FITS input or camera-capture controls. `focus monitor` consumes the camera-owned live-frame path, may be bounded with `--frames N`, supports `--no-audio` for deliberate silent operation, and deliberately rejects global `--json` with one structured error rather than creating an NDJSON stream.
- `pointing` exposes only `solve` and `goto`; older names such as `sync`, `init`, `where`, `calibrate`, `recover`, `status`, and `diagnose` are not part of the current parser.

## Stability rule

Command names, primary flags, JSON field names, and exit-code semantics are public automation surface once relied upon. Prefer additive evolution. A refactor must characterize existing observable CLI behaviour before changing plumbing.

When this document and executable help differ, treat that as documentation drift: current code/tests define implemented behaviour and this file should be corrected rather than inventing compatibility for stale prose.
