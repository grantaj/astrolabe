"""Frozen `astrolabe view` header serialisations.

Generated 2026-08-22 with astropy 7.2.0 via `hdul[0].header.tostring(sep="\\n")`,
the exact output `view` emitted before the FITS boundary was brought in-repo.
Each entry is (data-unit bytes, cards); the cards reconstruct the source header
block exactly, so fixtures are rebuilt rather than stored as binary.
Do not regenerate: this is the frozen CLI contract for the JSON `header` field.
"""

from __future__ import annotations

FITS_HEADER_GOLDENS: dict[str, tuple[int, tuple[str, ...]]] = {
    "image2d": (
        24,
        (
            "SIMPLE  =                    T / conforms to FITS standard                      ",
            "BITPIX  =                   16 / array data type                                ",
            "NAXIS   =                    2 / number of array dimensions                     ",
            "NAXIS1  =                    4                                                  ",
            "NAXIS2  =                    3                                                  ",
            "EXTEND  =                    T                                                  ",
            "OBJECT  = 'M42     '                                                            ",
            "COMMENT synthetic frame                                                         ",
            "HISTORY generated for golden tests                                              ",
            "END                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    ",
        ),
    ),
    "naxis0": (
        0,
        (
            "SIMPLE  =                    T / conforms to FITS standard                      ",
            "BITPIX  =                    8 / array data type                                ",
            "NAXIS   =                    0 / number of array dimensions                     ",
            "EXTEND  =                    T                                                  ",
            "END                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         ",
        ),
    ),
    "oned": (
        10,
        (
            "SIMPLE  =                    T / conforms to FITS standard                      ",
            "BITPIX  =                   16 / array data type                                ",
            "NAXIS   =                    1 / number of array dimensions                     ",
            "NAXIS1  =                    5                                                  ",
            "EXTEND  =                    T                                                  ",
            "END                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        ",
        ),
    ),
    "cube3d": (
        16,
        (
            "SIMPLE  =                    T / conforms to FITS standard                      ",
            "BITPIX  =                   16 / array data type                                ",
            "NAXIS   =                    3 / number of array dimensions                     ",
            "NAXIS1  =                    2                                                  ",
            "NAXIS2  =                    2                                                  ",
            "NAXIS3  =                    2                                                  ",
            "EXTEND  =                    T                                                  ",
            "END                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      ",
        ),
    ),
    "u16": (
        24,
        (
            "SIMPLE  =                    T / conforms to FITS standard                      ",
            "BITPIX  =                   16 / array data type                                ",
            "NAXIS   =                    2 / number of array dimensions                     ",
            "NAXIS1  =                    4                                                  ",
            "NAXIS2  =                    3                                                  ",
            "EXTEND  =                    T                                                  ",
            "BSCALE  =                    1                                                  ",
            "BZERO   =                32768                                                  ",
            "END                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     ",
        ),
    ),
    "bigheader": (
        8,
        (
            "SIMPLE  =                    T / conforms to FITS standard                      ",
            "BITPIX  =                   16 / array data type                                ",
            "NAXIS   =                    2 / number of array dimensions                     ",
            "NAXIS1  =                    2                                                  ",
            "NAXIS2  =                    2                                                  ",
            "EXTEND  =                    T                                                  ",
            "KEY000  =                    0                                                  ",
            "KEY001  =                    1                                                  ",
            "KEY002  =                    2                                                  ",
            "KEY003  =                    3                                                  ",
            "KEY004  =                    4                                                  ",
            "KEY005  =                    5                                                  ",
            "KEY006  =                    6                                                  ",
            "KEY007  =                    7                                                  ",
            "KEY008  =                    8                                                  ",
            "KEY009  =                    9                                                  ",
            "KEY010  =                   10                                                  ",
            "KEY011  =                   11                                                  ",
            "KEY012  =                   12                                                  ",
            "KEY013  =                   13                                                  ",
            "KEY014  =                   14                                                  ",
            "KEY015  =                   15                                                  ",
            "KEY016  =                   16                                                  ",
            "KEY017  =                   17                                                  ",
            "KEY018  =                   18                                                  ",
            "KEY019  =                   19                                                  ",
            "KEY020  =                   20                                                  ",
            "KEY021  =                   21                                                  ",
            "KEY022  =                   22                                                  ",
            "KEY023  =                   23                                                  ",
            "KEY024  =                   24                                                  ",
            "KEY025  =                   25                                                  ",
            "KEY026  =                   26                                                  ",
            "KEY027  =                   27                                                  ",
            "KEY028  =                   28                                                  ",
            "KEY029  =                   29                                                  ",
            "END                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         ",
        ),
    ),
}


def golden_header_text(name: str) -> str:
    """The exact string astropy returned for this fixture."""
    return "\n".join(FITS_HEADER_GOLDENS[name][1])


def golden_fits_bytes(name: str) -> bytes:
    """Rebuild the fixture: verbatim header block plus a zeroed data unit."""
    data_bytes, cards = FITS_HEADER_GOLDENS[name]
    header = "".join(card[:80].ljust(80) for card in cards)
    header = header.ljust(-(-len(header) // 2880) * 2880).encode("ascii")
    return header + bytes(-(-data_bytes // 2880) * 2880 if data_bytes else 0)
