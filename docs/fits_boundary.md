# FITS boundary

Astrolabe owns a deliberately narrow FITS read/write boundary in
`astrolabe.camera.pixels`, with no FITS dependency behind it. This document
records what that boundary covers and the header contract `astrolabe view`
exposes.

## Current surface

```text
PixelFrame(pixels, saturation_level)

load_fits_pixels(path)        -> PixelFrame
load_fits_bytes(data)         -> PixelFrame
image_to_pixels(Image)        -> PixelFrame
load_fits_header_cards(path)  -> list[str]
fits_image_bytes(pixels, *, extra_header=None, extra_cards=None) -> bytes
write_fits_image(path, pixels, *, extra_header=None, extra_cards=None) -> Path
```

Scope is a **simple 2D primary image**: `SIMPLE`/`BITPIX`/`NAXIS`/`NAXIS1`/
`NAXIS2`/`END`, 80-character cards, 2880-byte block padding, big-endian data,
`BITPIX` 8/16/32/-32/-64, and `BSCALE`/`BZERO` scaling (including the
signed-plus-`BZERO` form INDI cameras use for unsigned 16-bit frames).

Encoding is **value-preserving, not dtype-preserving**. Unsigned 16-bit input is
written in the standard signed-plus-`BZERO` form and therefore reads back as
`float64` with identical values; every other supported dtype reads back as the
big-endian view of itself. Consumers that need a specific dtype must cast.

`extra_header` emits typed cards; `extra_cards` copies already-formatted cards
through verbatim, so a caller can preserve metadata it read from a source file
without re-inferring each value's FITS type. Neither may name a keyword the
encoder derives from the array itself (`SIMPLE`, `BITPIX`, `NAXIS`, `NAXISn`,
`BSCALE`, `BZERO`, `EXTEND`, `END`): a duplicate would be appended after the
mandatory cards and win when the reader builds its header dict.

Explicitly out of scope: extensions and HDU lists, tables, compression,
continued/hierarch cards, and any WCS evaluation. A WCS-tagged frame may be
*written* by passing header cards through `extra_header`, but Astrolabe does not
interpret them. Callers needing more than this should own the extra behaviour
locally rather than widening this module.

Failures raise `ValueError` with the offending source, keyword or value named.
Header keywords are case-insensitive and must be at most 8 alphanumeric/`_`/`-`
characters; all header text must be printable ASCII.

## The `view` header field

`astrolabe view` emits `load_fits_header_cards()` joined by newlines as its JSON
`header` field: the file's primary header, in file order, where

- cards are right-stripped (not padded to 80 columns, as they were before the
  boundary was brought in-repo);
- wholly blank padding cards are dropped;
- the structural `END` card is excluded.

Card order, comments, and non-`KEY= VALUE` cards such as `COMMENT`/`HISTORY` are
preserved. Automation that parses by keyword is unaffected; automation depending
on fixed 80-column card widths must strip or pad.

`view` no longer emits `dependency_missing`/exit 2: the boundary has no optional
dependency to be missing. `view` still decodes the data unit on every
invocation, not only under `--show`, so a file whose header is readable but
whose `SIMPLE`/`NAXIS` declaration or payload length is wrong still fails with
`view_failed` exactly as before.
