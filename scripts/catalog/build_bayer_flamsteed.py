"""Regenerate ``data/bayer_flamsteed.csv`` from archival CDS catalogues.

The default inputs identify the Bright Star Catalogue, 5th Revised Edition
(CDS V/50) and the Hipparcos main catalogue (CDS I/239). V/50 supplies the
Bayer/Flamsteed ``Name`` and HD identifier; I/239 supplies the deterministic
HD-to-HIP crosswalk. The output is canonicalized, de-duplicated, and sorted.

Local copies may be supplied with ``--source`` and ``--hip-source`` so the same
path can be exercised without network access.
"""

import argparse
from pathlib import Path

from astrolabe.services.target.update import (
    BSC_CATALOG_ID,
    BSC_DEFAULT_URL,
    HIPPARCOS_CATALOG_ID,
    HIPPARCOS_DEFAULT_URLS,
    update_bsc_crosswalk,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_OUTPUT = _REPO_ROOT / "data" / "bayer_flamsteed.csv"


def build(
    *,
    source: str,
    hip_source: str,
    output: str | Path,
    verify_ssl: bool = True,
) -> dict:
    return update_bsc_crosswalk(
        source=source,
        hip_source=hip_source,
        output_path=str(output),
        verify_ssl=verify_ssl,
        show_progress=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="build_bayer_flamsteed")
    parser.add_argument(
        "--source",
        default=BSC_DEFAULT_URL,
        help=f"BSC source URL or local TSV (default: CDS {BSC_CATALOG_ID})",
    )
    parser.add_argument(
        "--hip-source",
        default=HIPPARCOS_DEFAULT_URLS[0],
        help=(
            "Hipparcos source URL or local catalog "
            f"(default: CDS {HIPPARCOS_CATALOG_ID})"
        ),
    )
    parser.add_argument(
        "--output",
        default=str(_DEFAULT_OUTPUT),
        help="Output path (default: repository data/bayer_flamsteed.csv)",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable SSL certificate verification (not recommended)",
    )
    args = parser.parse_args()

    meta = build(
        source=args.source,
        hip_source=args.hip_source,
        output=args.output,
        verify_ssl=not args.insecure,
    )
    print("Bayer/Flamsteed generation complete.")
    print(f"BSC source: {meta['source']} ({meta['source_catalog']})")
    print(f"Hipparcos source: {meta['hip_source']} ({meta['hip_source_catalog']})")
    print(f"Output: {meta['output_path']}")
    print(f"Aliases: {meta['aliases_written']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
