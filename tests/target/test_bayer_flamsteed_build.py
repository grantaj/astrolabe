import csv
from pathlib import Path
import subprocess
import sys


def _make_hip_line(hip_id: int, hd: int) -> str:
    buf = [" "] * 500
    hip_str = f"{hip_id:>6}"
    hd_str = f"{hd:>6}"
    buf[8 : 8 + len(hip_str)] = list(hip_str)
    buf[390 : 390 + len(hd_str)] = list(hd_str)
    return "".join(buf)


def test_build_bayer_flamsteed_from_local_archival_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    hip_source = tmp_path / "hip_main.dat"
    hip_source.write_text(_make_hip_line(32349, 48915) + "\n", encoding="utf-8")
    bsc_source = tmp_path / "bsc.tsv"
    bsc_source.write_text("Name\tHD\n9Alp CMa\t48915\n", encoding="utf-8")
    output = tmp_path / "bayer_flamsteed.csv"
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "catalog"
        / "build_bayer_flamsteed.py"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--source",
            str(bsc_source),
            "--hip-source",
            str(hip_source),
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Aliases: 4" in result.stdout
    with open(output, "r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert {(row["alias"], row["hip_id"]) for row in rows} == {
        ("9 canis majoris", "32349"),
        ("9 cma", "32349"),
        ("alpha canis majoris", "32349"),
        ("alpha cma", "32349"),
    }
