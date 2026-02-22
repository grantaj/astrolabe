import pytest

from astrolabe.services.target.update import _parse_hipparcos_line, update_hipparcos


def _put(buf: list[str], start: int, end: int, value: str) -> None:
    for idx, ch in enumerate(value):
        pos = start + idx
        if pos >= end:
            break
        buf[pos] = ch


def _make_line(hip_id: int, vmag: float, ra: float, dec: float) -> str:
    buf = [" "] * 120
    _put(buf, 8, 14, f"{hip_id:>6}")
    _put(buf, 41, 46, f"{vmag:5.2f}")
    _put(buf, 51, 63, f"{ra:12.6f}")
    _put(buf, 64, 76, f"{dec:12.6f}")
    return "".join(buf)


def test_parse_hipparcos_line():
    line = _make_line(32349, -1.46, 101.287155, -16.716116)
    record = _parse_hipparcos_line(line)
    assert record is not None
    assert record["hip_id"] == "32349"
    assert record["ra_deg"] == pytest.approx(101.287155)
    assert record["dec_deg"] == pytest.approx(-16.716116)
    assert record["mag"] == pytest.approx(-1.46)


def test_update_hipparcos_filters_by_mag(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    source = tmp_path / "hip_main.dat"
    source.write_text(
        "\n".join(
            [
                _make_line(32349, -1.46, 101.287155, -16.716116),
                _make_line(91262, 1.50, 279.234734, 38.783688),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    output = tmp_path / "hip_subset.csv"
    meta = update_hipparcos(source=str(source), output_path=str(output), max_mag=1.0)
    assert meta["stars_written"] == 1
    assert output.exists()

    content = output.read_text(encoding="utf-8")
    assert "32349" in content
    assert "91262" not in content
