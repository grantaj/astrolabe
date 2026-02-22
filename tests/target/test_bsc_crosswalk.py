import csv
from pathlib import Path

from astrolabe.services.target.update import (
    _aliases_from_bsc_name,
    _load_hd_to_hip,
    update_bsc_crosswalk,
)


def _make_hip_line(hip_id: int, hd: int) -> str:
    buf = [" "] * 500
    hip_str = f"{hip_id:>6}"
    hd_str = f"{hd:>6}"
    buf[8 : 8 + len(hip_str)] = list(hip_str)
    buf[390 : 390 + len(hd_str)] = list(hd_str)
    return "".join(buf)


def test_aliases_from_bsc_name():
    assert _aliases_from_bsc_name("Gam Cru") == ["gamma cru", "gamma crux"]
    assert _aliases_from_bsc_name("Alp Cen") == ["alpha cen", "alpha centaurus"]


def test_update_bsc_crosswalk_with_local_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    hip_path = tmp_path / "hip_main.dat"
    hip_path.write_text(_make_hip_line(61084, 108248), encoding="utf-8")

    bsc_path = tmp_path / "bsc.tsv"
    bsc_path.write_text(
        "# Dummy header\nName\tHD\nGam Cru\t108248\n",
        encoding="utf-8",
    )

    output = tmp_path / "bsc_crosswalk.csv"
    meta = update_bsc_crosswalk(
        source=str(bsc_path),
        hip_source=str(hip_path),
        output_path=str(output),
        verify_ssl=True,
        show_progress=False,
    )
    assert meta["aliases_written"] == 2

    with open(output, "r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["alias"] == "gamma cru"
    assert rows[0]["hip_id"] == "61084"
