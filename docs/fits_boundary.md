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
fits_header_text(path)        -> str
validate_fits_structure(path) -> None
fits_image_bytes(pixels, *, extra_header=None, extra_cards=None) -> bytes
write_fits_image(path, pixels, *, extra_header=None, extra_cards=None) -> Path
```

Scope is a **simple 2D primary image**: `SIMPLE`/`BITPIX`/`NAXIS`/`NAXIS1`/
`NAXIS2`/`END`, 80-character cards, 2880-byte block padding, big-endian data,
`BITPIX` 8/16/32/64/-32/-64, and `BSCALE`/`BZERO` scaling (including the
signed-plus-`BZERO` form INDI cameras use for unsigned 16-bit frames). `SIMPLE`
must be the primary header's first keyword.

Path-based readers transparently accept gzip streams detected by magic bytes.
Other compressed transports and compression inside FITS remain out of scope.

Encoding is **value-preserving, not dtype-preserving**. Unsigned 16-bit input is
written in the standard signed-plus-`BZERO` form and therefore reads back as
`float64` with identical values; every other supported dtype reads back as the
big-endian view of itself. Consumers that need a specific dtype must cast. The
writer accepts either byte order, so reader output is always valid writer input.

`extra_header` emits typed cards; `extra_cards` copies already-formatted cards
through verbatim, so a caller can preserve metadata it read from a source file
without re-inferring each value's FITS type. Neither may name a keyword the
encoder derives from the array itself (`SIMPLE`, `BITPIX`, `NAXIS`, `NAXISn`,
`BSCALE`, `BZERO`, `EXTEND`, `END`): a duplicate would be appended after the
mandatory cards and win when the reader builds its header dict.

Explicitly out of scope: extensions and HDU lists, tables, HDU compression,
continued/hierarch cards, and any WCS evaluation. A WCS-tagged frame may be
*written* by passing header cards through `extra_header`, but Astrolabe does not
interpret them. Callers needing more than this should own the extra behaviour
locally rather than widening this module.

Failures raise `ValueError` with the offending source, keyword or value named,
including a primary header that does not begin with `SIMPLE`.
Header keywords are case-insensitive and must be at most 8 alphanumeric/`_`/`-`
characters; all header text must be printable ASCII.

## The `view` header field

`astrolabe view` emits `fits_header_text()` as its JSON `header` field: every
80-column card of the primary header through `END`, newline-joined and padded so
the total length is a multiple of 2880. This is byte-identical to what `view`
emitted before the boundary was brought in-repo.

`load_fits_header_cards()` is the machine-facing accessor instead — right-stripped,
blank and `END` cards dropped — and is what callers extracting keywords should use.

## What `view` accepts

`view` validates primary-HDU *structure*, not pixel decodability: `SIMPLE` present,
first and true; `BITPIX` in the standard set 8/16/32/64/-32/-64; `NAXIS >= 0` with
non-negative `NAXISn`; and a data unit at least as long as the header declares.
Any dimensionality, including `NAXIS = 0`, is therefore accepted for header
inspection. `view --show` does require the decodable 2-D subset.

`view` no longer emits `dependency_missing`/exit 2: the boundary has no optional
dependency to be missing.
