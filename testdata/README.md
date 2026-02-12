# Test Data

This directory is used for local solver development and testing.

Large FITS files are **not committed to the repository**.

------------------------------------------------------------------------

## Workflow

1. **Start INDI server with simulator:**

       indiserver indi_simulator_ccd

2. **Generate simulated FITS files:**

       python scripts/gen_sim_fits.py --count 5 --exposure 2.0 --outdir testdata/raw

   This script will create star field FITS files for testing.

3. (Optional) Download additional sample images into:

       testdata/raw/

   Public sources for FITS files:
   - NASA FITS Support Office sample FITS page: https://fits.gsfc.nasa.gov/fits_samples.html
   - NOIRLab FITS Liberator datasets: https://noirlab.edu/public/products/applications/fitsliberator/datasets/

The `raw/` directory should be added to `.gitignore`.

------------------------------------------------------------------------

## Purpose

These images allow development of:

-   `SolverBackend`
-   CLI `solve` command
-   JSON output formatting
-   SolveResult parsing

without requiring a working camera or mount.

------------------------------------------------------------------------

## What Kind of Images to Use

For ASTAP testing, use:

-   Star field images (not spectra, flats, or calibration frames)
-   FITS format
-   Monochrome preferred
-   Wide field (guide camera style, 1--5° FOV)
-   Unsaturated stars
-   Typical exposure 1--10 seconds

Avoid:

-   Non-imaging FITS (tables, spectra, cubes)
-   Extremely narrow FOV (\<0.3°) unless specifically testing long focal
    length solving

------------------------------------------------------------------------

## Example Local Layout

    testdata/
        README.md
        raw/
            sample1.fits
            sample2.fits

------------------------------------------------------------------------

## Manual Test Procedure

Once images are generated or downloaded:

    astrolabe solve --in testdata/raw/sample1.fits

Expected result:

-   SolveResult printed
-   RA/Dec returned
-   RMS reported
-   JSON output valid (with --json)

------------------------------------------------------------------------

## Notes

These files are for development only and should not be committed.

If reproducible automated tests are desired later, consider hosting
small sample FITS files externally and downloading them in CI.
