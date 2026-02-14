"""
Generate a synthetic FITS star field using Gaia catalog for a QHY5III462 guide camera with a 120mm guide scope.
- Sensor: 1920x1080, 2.9um pixels
- Focal length: 120mm (wide field guiding)
- Pixel scale: ~5.0 arcsec/pixel
- FOV: ~2.66° x 1.50°
- Centered on RA=270°, Dec=0° (Milky Way region)

Requires the optional tools dependencies (install with `pip install -e .[tools]`).
"""
import csv
import gzip
import numpy as np
from pathlib import Path
from astropy.io import fits
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
from astropy.time import Time
from astroquery.vizier import Vizier, Conf as VizierConf
import astropy.units as u
from math import sqrt

# Camera and field parameters
# Use full sensor size unless you explicitly want a smaller FOV.
width, height = 1920, 1080
pixel_size_um = 2.9
focal_length_mm = 120  # wide field guide scope
# Corrected pixel scale formula (arcsec/pixel)
pixel_scale = 206.265 * pixel_size_um / focal_length_mm  # arcsec/pixel
fov_x = width * pixel_scale / 3600  # deg
fov_y = height * pixel_scale / 3600  # deg

print(f"DEBUG: pixel_scale = {pixel_scale:.6f} arcsec/pixel")
print(f"DEBUG: fov_x = {fov_x:.6f} deg, fov_y = {fov_y:.6f} deg")

# Center of field (Galactic center region)
ra_center = 266.4  # deg (Galactic center)
dec_center = -29.0   # deg (Galactic center)

# Calculate radius for cone search (half the diagonal of the FOV)
diag_deg = sqrt(fov_x**2 + fov_y**2)
radius_deg = diag_deg / 2
print(f"DEBUG: Using cone search with radius = {radius_deg:.3f} deg")
mag_limit = 18.0
row_limit = -1  # -1 means no limit in astroquery.vizier
max_stars = 1000

print(
    f"Field center RA={ra_center} deg, Dec={dec_center} deg, "
    f"FOV={fov_x:.2f} x {fov_y:.2f} deg, mag < {mag_limit}"
)
tycho_dir = Path("tycho2")
hyg_path = Path("hyg4.2/hygdata_v42.csv")
cache_dir = Path("testdata")
cache_dir.mkdir(parents=True, exist_ok=True)
cache_name = f"gaia_cache_ra{ra_center}_dec{dec_center}_rad{radius_deg:.3f}_g{mag_limit}.npz"
cache_path = cache_dir / cache_name

# Load Tycho-2 if available; fallback to HYG, then Gaia/VizieR.
tycho_files = sorted(tycho_dir.glob("tyc2.dat.*.gz"))
if tycho_files:
    print(f"Loading Tycho-2 catalog from {tycho_dir} ({len(tycho_files)} files)")
    ra_list: list[float] = []
    dec_list: list[float] = []
    mag_list: list[float] = []

    ra0 = np.deg2rad(ra_center)
    dec0 = np.deg2rad(dec_center)
    r_deg = radius_deg

    def parse_mag(line: str) -> float | None:
        vt = line[123:129].strip()
        bt = line[110:116].strip()
        if vt:
            try:
                return float(vt)
            except ValueError:
                return None
        if bt:
            try:
                return float(bt)
            except ValueError:
                return None
        return None

    for path in tycho_files:
        with gzip.open(path, "rt", encoding="ascii", errors="ignore") as f:
            for line in f:
                mag = parse_mag(line)
                if mag is None or mag > mag_limit:
                    continue
                try:
                    ra = float(line[15:27])
                    dec = float(line[28:40])
                except ValueError:
                    continue
                # Cone filter inline to avoid huge arrays.
                ra_rad = np.deg2rad(ra)
                dec_rad = np.deg2rad(dec)
                cos_sep = (
                    np.sin(dec0) * np.sin(dec_rad)
                    + np.cos(dec0) * np.cos(dec_rad) * np.cos(ra_rad - ra0)
                )
                sep_deg = np.rad2deg(np.arccos(np.clip(cos_sep, -1.0, 1.0)))
                if sep_deg > r_deg:
                    continue
                ra_list.append(ra)
                dec_list.append(dec)
                mag_list.append(mag)

    ra_arr = np.array(ra_list, dtype=float)
    dec_arr = np.array(dec_list, dtype=float)
    mag_arr = np.array(mag_list, dtype=float)
    print(f"Tycho-2 after cone filter: {len(ra_arr)} stars.")
elif hyg_path.exists():
    print(f"Loading HYG catalog: {hyg_path}")
    ra_list: list[float] = []
    dec_list: list[float] = []
    mag_list: list[float] = []
    with hyg_path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                mag = float(row["mag"])
                if mag > mag_limit:
                    continue
                # Prefer radians if present to avoid RA unit ambiguity.
                if row.get("rarad") and row.get("decrad"):
                    ra = np.rad2deg(float(row["rarad"]))
                    dec = np.rad2deg(float(row["decrad"]))
                else:
                    ra = float(row["ra"])
                    dec = float(row["dec"])
            except (KeyError, ValueError):
                continue
            ra_list.append(ra)
            dec_list.append(dec)
            mag_list.append(mag)
    ra_arr = np.array(ra_list, dtype=float)
    dec_arr = np.array(dec_list, dtype=float)
    mag_arr = np.array(mag_list, dtype=float)
    print(f"HYG returned {len(ra_arr)} stars with mag <= {mag_limit}.")

    # Apply cone filter to match FOV.
    ra0 = np.deg2rad(ra_center)
    dec0 = np.deg2rad(dec_center)
    ra_rad = np.deg2rad(ra_arr)
    dec_rad = np.deg2rad(dec_arr)
    cos_sep = np.sin(dec0) * np.sin(dec_rad) + np.cos(dec0) * np.cos(dec_rad) * np.cos(ra_rad - ra0)
    sep_deg = np.rad2deg(np.arccos(np.clip(cos_sep, -1.0, 1.0)))
    mask = sep_deg <= radius_deg
    ra_arr = ra_arr[mask]
    dec_arr = dec_arr[mask]
    mag_arr = mag_arr[mask]
    print(f"HYG after cone filter: {len(ra_arr)} stars.")
else:
    # Query Gaia for stars in the field (with local cache)
    VizierConf.row_limit = row_limit
    VizierConf.timeout = 300
    VizierConf.server = "vizier.cfa.harvard.edu"  # alt mirror; swap if needed
    if cache_path.exists():
        data = np.load(cache_path)
        ra_arr = data["ra"]
        dec_arr = data["dec"]
        mag_arr = data["mag"]
        print(f"Loaded {len(ra_arr)} stars from cache: {cache_path}")
    else:
        try:
            result = Vizier(
                columns=["RA_ICRS", "DE_ICRS", "Gmag"],
                column_filters={"Gmag": f"<{mag_limit}"},
                row_limit=row_limit,
                timeout=300,
                vizier_server=VizierConf.server,
            ).query_region(
                SkyCoord(ra_center, dec_center, unit="deg"),
                radius=radius_deg * u.deg, catalog="I/355/gaiadr3"
            )
        except Exception as e:
            print(f"Catalog query failed (possible network issue): {e}")
            exit(2)
        if not result:
            print("Catalog query succeeded, but no stars found in the region. Try increasing FOV or Gmag limit.")
            exit(1)
        stars = result[0]
        print(f"Catalog returned {len(stars)} stars (row_limit={row_limit}).")
        if len(stars) > 0:
            print("First 5 stars:")
            print(stars[:5])

        ra_arr = np.array(stars["RA_ICRS"], dtype=float)
        dec_arr = np.array(stars["DE_ICRS"], dtype=float)
        mag_arr = np.array(stars["Gmag"], dtype=float)
        np.savez_compressed(cache_path, ra=ra_arr, dec=dec_arr, mag=mag_arr)
        print(f"Wrote cache: {cache_path}")

# Keep only the brightest stars for a solvable, not-overcrowded field.
if len(mag_arr) > max_stars:
    idx = np.argsort(mag_arr)
    idx = idx[:max_stars]
    ra_arr = ra_arr[idx]
    dec_arr = dec_arr[idx]
    mag_arr = mag_arr[idx]
    print(f"Downselected to {len(mag_arr)} brightest stars (max_stars={max_stars}).")

# If the catalog is too sparse (e.g., HYG in a small FOV), fill with synthetic stars.

# Create image
image = np.zeros((height, width), dtype=np.float32)

# WCS setup
w = WCS(naxis=2)
w.wcs.crpix = [width/2, height/2]
w.wcs.cdelt = np.array([-pixel_scale/3600, pixel_scale/3600])  # deg/pix
w.wcs.crval = [ra_center, dec_center]
w.wcs.ctype = ["RA---TAN", "DEC--TAN"]

# Render stars
y_grid, x_grid = np.ogrid[:height, :width]
mag_zero_point = 10.0
flux_at_mag0 = 60000.0
base_sigma = 1.6
for ra, dec, mag in zip(ra_arr, dec_arr, mag_arr):
    x, y = w.wcs_world2pix([[ra, dec]], 0)[0]
    x = int(round(x))
    y = int(round(y))
    if 0 <= x < width and 0 <= y < height:
        flux = flux_at_mag0 * 10 ** (-0.4 * (mag - mag_zero_point))
        sigma = base_sigma + 0.15 * max(mag - mag_zero_point, 0)
        image += flux * np.exp(-((x_grid - x) ** 2 + (y_grid - y) ** 2) / (2 * sigma**2))

# Add background + noise
background_level = 800.0
read_noise = 4.0
image += background_level
image += np.random.normal(0, read_noise, image.shape)

# Auto-scale to 16-bit range for visibility in most FITS viewers.
# Scale based on star signal above the background to avoid amplifying noise.
target_max = 60000.0
signal = image - background_level
peak = float(signal.max())
if peak > 0:
    image = background_level + signal * (target_max / peak)
image = np.clip(image, 0, 65535).astype(np.uint16)

# FITS header
hdr = fits.Header()
hdr["SIMPLE"] = True
hdr["BITPIX"] = 16
hdr["NAXIS"] = 2
hdr["NAXIS1"] = width
hdr["NAXIS2"] = height
hdr["CRPIX1"] = w.wcs.crpix[0]
hdr["CRPIX2"] = w.wcs.crpix[1]
hdr["CRVAL1"] = w.wcs.crval[0]
hdr["CRVAL2"] = w.wcs.crval[1]
hdr["CDELT1"] = w.wcs.cdelt[0]
hdr["CDELT2"] = w.wcs.cdelt[1]
hdr["CTYPE1"] = w.wcs.ctype[0]
hdr["CTYPE2"] = w.wcs.ctype[1]
hdr["DATE-OBS"] = Time.now().isot

hdu = fits.PrimaryHDU(image, header=hdr)
hdu.writeto("synthetic_qhy5iii462_starfield.fits", overwrite=True)
print(f"Wrote synthetic_qhy5iii462_starfield.fits with {len(mag_arr)} stars")
