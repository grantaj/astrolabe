"""Deterministic behaviour of the local-catalogue starfield generator.

The generator lives in `scripts/`, so it is loaded by path.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pytest

from astrolabe.camera.pixels import load_fits_header_cards, load_fits_pixels

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gen_catalog_starfield.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_catalog_starfield", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gen = _load_generator()


@pytest.fixture
def field():
    return gen.Field(width_px=64, height_px=48, max_stars=10)


# Frozen from the astropy WCS this tool replaced, generated 2026-08-22 with
# astropy 7.2.0 for the default Field (RA---TAN, CRVAL 266.4/-29.0,
# CRPIX 960/540, CDELT -+0.0013846493055555554 deg/px, zero-based pixels).
_TAN_REFERENCE = (
    (266.4, -29.0, 959.0, 538.9999999999975),
    (267.0, -28.5, 578.1649894051109, 899.1599093088835),
    (265.2, -29.9, 1710.4548480553185, -114.9608762068109),
    (266.4, -28.25, 958.9999999999999, 1080.6843360636526),
    (265.0, -29.0, 1843.4300033564086, 533.761201282018),
)


@pytest.mark.parametrize(("ra_deg", "dec_deg", "x_px", "y_px"), _TAN_REFERENCE)
def test_tan_projection_matches_frozen_wcs_reference(ra_deg, dec_deg, x_px, y_px):
    x, y = gen.tan_world_to_pixel(np.array([ra_deg]), np.array([dec_deg]), gen.Field())

    # 1e-6 px: the reference carries astropy's own float noise (centre is
    # 538.9999999999975).
    assert abs(float(x[0]) - x_px) < 1e-6
    assert abs(float(y[0]) - y_px) < 1e-6


def test_field_geometry_is_derived_from_optics():
    full = gen.Field()

    assert full.pixel_scale_arcsec == pytest.approx(4.9847375)
    assert full.fov_x_deg == pytest.approx(2.65852667, abs=1e-8)
    assert full.fov_y_deg == pytest.approx(1.49542125, abs=1e-8)
    assert full.cdelt == (
        -full.pixel_scale_arcsec / 3600.0,
        full.pixel_scale_arcsec / 3600.0,
    )


def test_render_field_is_deterministic_for_a_seed(field):
    catalog = gen.Catalog(
        ra_deg=np.array([266.4, 266.42]),
        dec_deg=np.array([-29.0, -28.99]),
        mag=np.array([6.0, 9.5]),
    )

    first = gen.render_field(field, catalog, seed=7)
    second = gen.render_field(field, catalog, seed=7)
    different = gen.render_field(field, catalog, seed=8)

    assert first.dtype == np.uint16
    assert first.shape == (48, 64)
    assert np.array_equal(first, second)
    assert not np.array_equal(first, different)


def test_generate_writes_a_readable_wcs_tagged_fits(tmp_path, field):
    catalog = gen.Catalog(
        ra_deg=np.array([266.4]), dec_deg=np.array([-29.0]), mag=np.array([5.0])
    )

    path = gen.generate(field, catalog, tmp_path / "star.fits", seed=3)
    frame = load_fits_pixels(path)
    cards = load_fits_header_cards(path)

    assert frame.pixels.shape == (48, 64)
    assert np.array_equal(frame.pixels, gen.render_field(field, catalog, seed=3))
    assert "CTYPE1  = 'RA---TAN'" in cards
    assert "CTYPE2  = 'DEC--TAN'" in cards
    assert any(card.startswith("CRVAL1  =") and "266.4" in card for card in cards)


def test_load_catalog_prefers_local_sources_without_network(tmp_path, field):
    cache = tmp_path / "cache.npz"
    np.savez(
        cache,
        ra=np.array([266.4, 10.0]),
        dec=np.array([-29.0, 10.0]),
        mag=np.array([7.0, 2.0]),
    )

    catalog, source = gen.load_catalog(
        field,
        tycho_dir=tmp_path / "absent",
        hyg_path=tmp_path / "absent.csv",
        cache_path=cache,
    )

    assert "cache" in source
    assert len(catalog) == 1
    assert catalog.ra_deg[0] == pytest.approx(266.4)


def test_load_catalog_fails_actionably_when_no_local_catalogue_exists(tmp_path, field):
    with pytest.raises(gen.NoCatalogError) as excinfo:
        gen.load_catalog(
            field,
            tycho_dir=tmp_path / "absent",
            hyg_path=tmp_path / "absent.csv",
            cache_path=tmp_path / "absent.npz",
        )

    message = str(excinfo.value)
    assert "does not query catalogues over the network" in message
    assert "--tycho-dir" in message
    assert "--hyg" in message
    assert "--cache" in message


def test_load_catalog_reads_hyg_csv_and_keeps_brightest(tmp_path, field):
    hyg = tmp_path / "hyg.csv"
    # HYG 'ra' is decimal hours: 17.76 h == 266.4 deg.
    hyg.write_text(
        "ra,dec,mag\n"
        "17.760000,-29.00,6.0\n"
        "17.760667,-29.01,4.0\n"
        "0.666667,10.00,1.0\n"
        "17.761333,-29.02,not-a-number\n"
    )

    catalog, source = gen.load_catalog(
        field,
        tycho_dir=tmp_path / "absent",
        hyg_path=hyg,
        cache_path=tmp_path / "absent.npz",
    )

    assert "HYG" in source
    assert list(catalog.mag) == [4.0, 6.0]


def test_load_hyg_converts_hours_to_degrees(tmp_path, field):
    hyg = tmp_path / "hours.csv"
    hyg.write_text("ra,dec,mag\n17.76,-29.0,5.0\n")

    catalog = gen.load_hyg(field, hyg)

    assert catalog.ra_deg[0] == pytest.approx(266.4)
    assert catalog.dec_deg[0] == pytest.approx(-29.0)


def test_load_hyg_prefers_radian_columns_when_present(tmp_path, field):
    hyg = tmp_path / "radians.csv"
    hyg.write_text(
        "ra,dec,rarad,decrad,mag\n"
        f"0.0,0.0,{math.radians(266.4)!r},{math.radians(-29.0)!r},5.0\n"
    )

    catalog = gen.load_hyg(field, hyg)

    assert catalog.ra_deg[0] == pytest.approx(266.4)
    assert catalog.dec_deg[0] == pytest.approx(-29.0)
