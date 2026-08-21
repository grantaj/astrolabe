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

The topology below reflects current `main`. Use `--help` for exact arguments.

| Command | Subcommands / purpose | Current status |
| --- | --- | --- |
| `doctor` | local configuration/backend diagnostics | implemented |
| `capture` | capture one camera frame | implemented |
| `solve` | plate-solve a FITS image | implemented |
| `view` | inspect a FITS file; optional graphical display | implemented |
| `mount` | `status`, `slew`, `track`, `park`, `stop` | implemented |
| `resolve` | resolve target names/catalog IDs offline | implemented |
| `goto` | target resolution + closed-loop service, currently falling back to a plain mount slew | partial / fallback |
| `pointing` | `solve`, `sync`, `init`, `goto` | implemented |
| `align` | deprecated alias for `pointing` | compatibility alias |
| `polar` | N-pose polar-axis measurement/correction estimate | implemented |
| `focus` | `measure` multi-star HFR | implemented |
| `guide` | `calibrate`, `start`, `stop`, `status` | CLI present; service placeholder |
| `plan` | offline-first target planning | implemented |
| `update catalog` | all/default catalog updates; `openngc`, `hip`, `bsc` subsets | implemented |

### A few non-obvious current boundaries

- `view` takes its FITS input via `--in` on current `main`.
- `polar` requires an RA rotation and observer latitude; it also exposes exposure/settling and pose-count controls.
- `focus measure` accepts either `--in` FITS input or camera-capture controls. Continuous focus monitoring is not part of current `main` unless and until the corresponding feature PR is merged.
- `pointing` currently uses `solve`, `sync`, `init`, and `goto`; older names such as `where`, `calibrate`, `recover`, `status`, and `diagnose` are not part of the current parser.

## Stability rule

Command names, primary flags, JSON field names, and exit-code semantics are public automation surface once relied upon. Prefer additive evolution. A refactor must characterize existing observable CLI behaviour before changing plumbing.

When this document and executable help differ, treat that as documentation drift: current code/tests define implemented behaviour and this file should be corrected rather than inventing compatibility for stale prose.
