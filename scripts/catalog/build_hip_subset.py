"""Build hip_subset.csv from the archival Hipparcos I/239 source."""

import argparse

from astrolabe.services.target.update import update_hipparcos

_DEFAULT_MAX_MAG = 7.0


def main() -> int:
    parser = argparse.ArgumentParser(prog="build_hip_subset")
    parser.add_argument("--source", help="Hipparcos catalog source URL or path")
    parser.add_argument("--output", help="Output path for hip_subset.csv")
    parser.add_argument(
        "--max-mag",
        type=float,
        default=_DEFAULT_MAX_MAG,
        help=f"Maximum V magnitude to include (default: {_DEFAULT_MAX_MAG})",
    )
    args = parser.parse_args()

    meta = update_hipparcos(
        source=args.source,
        output_path=args.output,
        max_mag=args.max_mag,
    )
    print("Hipparcos subset update complete.")
    print(f"Source: {meta['source']}")
    print(f"Cache: {meta['cache_dir']}")
    print(f"Output: {meta['output_path']}")
    print(f"Stars: {meta['stars_written']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
