"""Golden/characterisation tests for the CLI output and exit-code contract.

Every assertion here is an *observable* fact about the CLI: stdout in
``--json`` mode, stdout + stderr in human mode, and the exit code. They are
the safety net for the CLI plumbing refactor and must not be relaxed.
"""

from __future__ import annotations

import json
import sys

import pytest

from fits_header_goldens import golden_fits_bytes, golden_header_text

from astrolabe.errors import NotImplementedFeature, ServiceError
from astrolabe.pointing import PointingResult
from astrolabe.services.guide import CalibrationResult, GuidingStatus
from astrolabe.services.polar.types import PolarResult
from golden import (
    FakeCamera,
    FakeMount,
    FakeSolver,
    envelope,
    patch_backends,
    run_cli,
    solve_result,
)


@pytest.fixture(autouse=True)
def _isolate_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture
def backends(monkeypatch):
    mount, camera, solver = FakeMount(), FakeCamera(), FakeSolver()
    patch_backends(monkeypatch, mount=mount, camera=camera, solver=solver)
    return mount, camera, solver


def _service(monkeypatch, name, **methods):
    class _Fake:
        def __init__(self, *args, **kwargs):
            pass

    for method, behaviour in methods.items():
        setattr(_Fake, method, behaviour)
    monkeypatch.setattr(f"astrolabe.cli.commands.{name}", _Fake)


def _raise(exc):
    def _method(self, *args, **kwargs):
        raise exc

    return _method


def _return(value):
    def _method(self, *args, **kwargs):
        return value

    return _method


# --------------------------------------------------------------------------
# version / help
# --------------------------------------------------------------------------


def test_version(monkeypatch, capsys):
    code, out, err = run_cli(monkeypatch, capsys, "--version")
    assert code == 0
    assert out.startswith("Astrolabe ")
    assert err == ""


def test_no_command_prints_help(monkeypatch, capsys):
    code, out, err = run_cli(monkeypatch, capsys)
    assert code == 0
    assert "usage: astrolabe" in out


def test_goto_help_hides_retired_centering_flags(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["astrolabe", "goto", "--help"])
    with pytest.raises(SystemExit) as exc:
        from astrolabe.cli.main import main

        main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "deprecated" in out
    assert "--tolerance-arcsec" not in out
    assert "--max-iterations" not in out


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------


@pytest.fixture
def doctor_env(monkeypatch, backends):
    monkeypatch.setattr(
        "astrolabe.cli.commands.socket.create_connection",
        lambda *a, **k: _Closable(),
    )
    return backends


class _Closable:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_doctor_json_ok(monkeypatch, capsys, doctor_env):
    code, out, err = run_cli(monkeypatch, capsys, "--json", "doctor")
    payload = envelope(out)
    assert code == 0
    assert payload["ok"] is True
    assert payload["command"] == "doctor"
    assert payload["error"] is None
    assert set(payload["data"]["checks"]) == {
        "config",
        "indi_server",
        "solver (astap)",
        "camera (indi)",
        "mount (indi)",
    }
    assert all(check["ok"] for check in payload["data"]["checks"].values())


def test_doctor_human_failure(monkeypatch, capsys, backends):
    mount, camera, solver = backends
    solver.available = False
    monkeypatch.setattr(
        "astrolabe.cli.commands.socket.create_connection",
        _raise_factory(ConnectionRefusedError()),
    )
    code, out, err = run_cli(monkeypatch, capsys, "doctor")
    assert code == 1
    assert out.startswith("Astrolabe Doctor Report\n=======================\n")
    assert "indi_server          : MISSING (not reachable)" in out
    assert "solver (astap)       : MISSING (found)" in out
    assert out.endswith("\nSome components are missing or not configured.\n")


def test_doctor_json_failure(monkeypatch, capsys, backends):
    mount, camera, solver = backends
    solver.available = False
    monkeypatch.setattr(
        "astrolabe.cli.commands.socket.create_connection",
        _raise_factory(ConnectionRefusedError()),
    )
    code, out, err = run_cli(monkeypatch, capsys, "--json", "doctor")
    payload = envelope(out)
    assert code == 1
    assert payload["ok"] is False
    assert payload["error"] == {
        "code": "doctor_failed",
        "message": "one or more checks failed",
        "details": None,
    }


def _raise_factory(exc):
    def _fn(*args, **kwargs):
        raise exc

    return _fn


def test_doctor_dry_run_notice(monkeypatch, capsys, doctor_env):
    code, out, err = run_cli(monkeypatch, capsys, "--dry-run", "doctor")
    assert code == 0
    assert err == "--dry-run has no effect for doctor.\n"


# --------------------------------------------------------------------------
# solve
# --------------------------------------------------------------------------


def test_solve_missing_path(monkeypatch, capsys, backends):
    code, out, err = run_cli(monkeypatch, capsys, "solve")
    assert code == 2
    assert out == ""
    assert err == "Input FITS file path is required.\n"


def test_solve_file_not_found(monkeypatch, capsys, backends):
    code, out, err = run_cli(monkeypatch, capsys, "solve", "/nope/missing.fits")
    assert code == 1
    assert err == "Input file not found: /nope/missing.fits\n"


def test_solve_json_success(monkeypatch, capsys, backends, tmp_path):
    fits = tmp_path / "frame.fits"
    fits.write_text("x")
    code, out, err = run_cli(monkeypatch, capsys, "--json", "solve", str(fits))
    payload = envelope(out)
    assert code == 0
    assert payload["ok"] is True
    assert payload["command"] == "solve"
    assert payload["error"] is None
    assert payload["data"]["ra_rad"] == 1.0
    assert payload["data"]["num_stars"] == 42


def test_solve_human_success(monkeypatch, capsys, backends, tmp_path):
    fits = tmp_path / "frame.fits"
    fits.write_text("x")
    code, out, err = run_cli(monkeypatch, capsys, "solve", str(fits))
    assert code == 0
    assert out == (
        "Success: True\n"
        "RA: 03:49:10.99\n"
        "Dec: +28:38:52.40\n"
        "Pixel scale: 1.25\n"
        "Rotation: 14.324°\n"
        "RMS: 0.4\n"
        "Stars: 42\n"
        "Message: solved\n"
    )


def test_solve_human_failure_verbose(monkeypatch, capsys, backends, tmp_path):
    _, _, solver = backends
    solver.result = solve_result(success=False)
    fits = tmp_path / "frame.fits"
    fits.write_text("x")
    code, out, err = run_cli(monkeypatch, capsys, "solve", str(fits), "--verbose")
    assert code == 1
    assert out == (
        "Success: False\n"
        "RA: None\n"
        "Dec: None\n"
        "Pixel scale: None\n"
        "Rotation: None\n"
        "RMS: None\n"
        "Stars: None\n"
        "Message: no stars\n"
        "\n--- ASTAP output ---\n"
        "RAW SOLVER TEXT\n"
    )


def test_solve_json_failure_verbose(monkeypatch, capsys, backends, tmp_path):
    _, _, solver = backends
    solver.result = solve_result(success=False)
    fits = tmp_path / "frame.fits"
    fits.write_text("x")
    code, out, err = run_cli(
        monkeypatch, capsys, "--json", "solve", str(fits), "--verbose"
    )
    payload = envelope(out)
    assert code == 1
    assert payload["ok"] is False
    assert payload["data"] is None
    assert payload["error"] == {
        "code": "solve_failed",
        "message": "no stars",
        "details": {"raw_output": "RAW SOLVER TEXT"},
    }


def test_solve_json_failure_quiet(monkeypatch, capsys, backends, tmp_path):
    _, _, solver = backends
    solver.result = solve_result(success=False)
    fits = tmp_path / "frame.fits"
    fits.write_text("x")
    code, out, err = run_cli(monkeypatch, capsys, "--json", "solve", str(fits))
    payload = envelope(out)
    assert code == 1
    assert payload["error"]["details"] is None


# --------------------------------------------------------------------------
# capture
# --------------------------------------------------------------------------


def test_capture_requires_exposure(monkeypatch, capsys, backends):
    code, out, err = run_cli(monkeypatch, capsys, "capture")
    assert code == 2
    assert err == (
        "Exposure is required (use --exposure or set camera.default_exposure_s).\n"
    )


def test_capture_bad_roi(monkeypatch, capsys, backends):
    code, out, err = run_cli(
        monkeypatch, capsys, "capture", "--exposure", "1", "--roi", "1,2"
    )
    assert code == 2
    assert err == "ROI must be in x,y,w,h format\n"


def test_capture_json(monkeypatch, capsys, backends, tmp_path):
    _, camera, _ = backends
    source = tmp_path / "src.fits"
    source.write_text("x")
    camera.path = str(source)
    out_path = tmp_path / "out" / "saved.fits"
    code, out, err = run_cli(
        monkeypatch,
        capsys,
        "--json",
        "capture",
        "--exposure",
        "2.5",
        "--out",
        str(out_path),
    )
    payload = envelope(out)
    assert code == 0
    assert payload["command"] == "capture"
    assert payload["ok"] is True
    assert payload["data"] == {
        "path": str(out_path),
        "exposure_s": 2.5,
        "timestamp_utc": "2026-01-02T03:04:05+00:00",
        "width_px": 100,
        "height_px": 200,
    }


def test_capture_human(monkeypatch, capsys, backends, tmp_path):
    _, camera, _ = backends
    camera.path = str(tmp_path / "frame.fits")
    code, out, err = run_cli(monkeypatch, capsys, "capture", "--exposure", "1.0")
    assert code == 0
    assert out == f"Saved: {tmp_path / 'frame.fits'}\nExposure: 1.0s\n"


# --------------------------------------------------------------------------
# view
# --------------------------------------------------------------------------


def test_view_file_not_found_human(monkeypatch, capsys):
    code, out, err = run_cli(monkeypatch, capsys, "view", "--in", "/nope/x.fits")
    assert code == 1
    assert err == "Input file not found: /nope/x.fits\n"


def test_view_file_not_found_json(monkeypatch, capsys):
    code, out, err = run_cli(
        monkeypatch, capsys, "--json", "view", "--in", "/nope/x.fits"
    )
    payload = envelope(out)
    assert code == 1
    assert payload["command"] == "view"
    assert payload["error"] == {
        "code": "file_not_found",
        "message": "Input file not found: /nope/x.fits",
        "details": None,
    }


def test_view_failure_json(monkeypatch, capsys, tmp_path):
    broken = tmp_path / "broken.fits"
    broken.write_text("not a fits file")
    code, out, err = run_cli(monkeypatch, capsys, "--json", "view", "--in", str(broken))
    payload = envelope(out)
    assert code == 1
    assert payload["error"]["code"] == "view_failed"
    assert payload["error"]["message"].startswith("Error viewing FITS file: ")


def _sample_fits(tmp_path):
    import numpy as np

    from astrolabe.camera.pixels import write_fits_image

    pixels = (np.arange(6).reshape(2, 3) * 1000).astype(np.uint16)
    path = write_fits_image(
        tmp_path / "frame.fits", pixels, extra_header={"OBJECT": "M42"}
    )
    return path, pixels


def test_view_reports_the_fits_header_json(monkeypatch, capsys, tmp_path):
    path, _ = _sample_fits(tmp_path)
    code, out, err = run_cli(monkeypatch, capsys, "--json", "view", "--in", str(path))
    payload = envelope(out)
    assert code == 0
    assert payload["data"]["path"] == str(path)
    assert payload["data"]["show"] is False
    header = payload["data"]["header"]
    assert isinstance(header, str)
    assert header.splitlines()[0] == "SIMPLE  =                    T".ljust(80)
    assert "NAXIS1  =                    3".ljust(80) in header
    assert "OBJECT  = 'M42     '".ljust(80) in header
    assert header.splitlines()[-1].startswith("END")
    assert len(header) % 2880 == 0


def test_view_reports_the_fits_header_human(monkeypatch, capsys, tmp_path):
    path, _ = _sample_fits(tmp_path)
    code, out, err = run_cli(monkeypatch, capsys, "view", "--in", str(path))
    assert code == 0
    assert out.startswith("FITS Header:\nSIMPLE  =")
    assert out.rstrip().endswith("END")


def test_view_rejects_a_valid_header_with_a_truncated_payload(
    monkeypatch, capsys, tmp_path
):
    """`view` decodes the data unit even without --show."""
    import numpy as np

    from astrolabe.camera.pixels import fits_image_bytes

    payload = fits_image_bytes(np.zeros((40, 40), dtype=np.uint16))
    truncated = tmp_path / "truncated.fits"
    truncated.write_bytes(payload[: len(payload) - 2880])

    code, out, err = run_cli(
        monkeypatch, capsys, "--json", "view", "--in", str(truncated)
    )
    payload_json = envelope(out)
    assert code == 1
    assert payload_json["error"]["code"] == "view_failed"


def test_view_rejects_a_header_block_without_simple(monkeypatch, capsys, tmp_path):
    junk = tmp_path / "junk.fits"
    cards = b"".join(
        [f"JUNK{i:<4}=                    {i}".ljust(80).encode() for i in range(35)]
    )
    junk.write_bytes((cards + b"END".ljust(80)).ljust(2880))

    code, out, err = run_cli(monkeypatch, capsys, "--json", "view", "--in", str(junk))
    payload_json = envelope(out)
    assert code == 1
    assert payload_json["error"]["code"] == "view_failed"


def test_view_rejects_a_header_not_beginning_with_simple(monkeypatch, capsys, tmp_path):
    misordered = tmp_path / "misordered.fits"
    cards = [
        "JUNK    =                    1",
        "SIMPLE  =                    T",
        "BITPIX  =                    8",
        "NAXIS   =                    2",
        "NAXIS1  =                    4",
        "NAXIS2  =                    3",
    ]
    header = "".join(card.ljust(80) for card in cards) + "END".ljust(80)
    misordered.write_bytes(header.ljust(2880).encode() + bytes(2880))

    code, out, err = run_cli(
        monkeypatch, capsys, "--json", "view", "--in", str(misordered)
    )
    payload_json = envelope(out)
    assert code == 1
    assert payload_json["error"]["code"] == "view_failed"


@pytest.mark.parametrize("name", ["naxis0", "oned", "cube3d", "image2d", "u16"])
def test_view_accepts_any_valid_primary_hdu(monkeypatch, capsys, tmp_path, name):
    """Non-graphical `view` inspects headers; it does not require decodable pixels."""
    path = tmp_path / f"{name}.fits"
    path.write_bytes(golden_fits_bytes(name))

    code, out, err = run_cli(monkeypatch, capsys, "--json", "view", "--in", str(path))
    payload_json = envelope(out)

    assert code == 0
    assert payload_json["data"]["header"] == golden_header_text(name)


def test_view_show_loads_pixel_data_without_astropy(monkeypatch, capsys, tmp_path):
    import numpy as np

    path, pixels = _sample_fits(tmp_path)
    shown = {}

    class FakePlt:
        def imshow(self, data, **kwargs):
            shown["data"] = data

        def title(self, text):
            pass

        def colorbar(self):
            pass

        def show(self):
            shown["shown"] = True

    monkeypatch.setitem(sys.modules, "matplotlib.pyplot", FakePlt())
    code, out, err = run_cli(
        monkeypatch, capsys, "--json", "view", "--in", str(path), "--show"
    )
    payload = envelope(out)
    assert code == 0
    assert payload["data"]["show"] is True
    assert shown["shown"] is True
    assert np.array_equal(shown["data"], pixels)


# --------------------------------------------------------------------------
# mount
# --------------------------------------------------------------------------


def test_mount_status_json(monkeypatch, capsys, backends):
    code, out, err = run_cli(monkeypatch, capsys, "--json", "mount", "status")
    payload = envelope(out)
    assert code == 0
    assert payload["command"] == "mount.status"
    assert payload["data"] == {
        "connected": True,
        "tracking": True,
        "slewing": False,
        "ra_rad": 1.0,
        "dec_rad": 0.5,
        "timestamp_utc": "2026-01-02T03:04:05+00:00",
    }


def test_mount_status_human(monkeypatch, capsys, backends):
    code, out, err = run_cli(monkeypatch, capsys, "mount", "status")
    assert code == 0
    assert out == (
        "Connected: True\n"
        "Tracking: True\n"
        "Slewing: False\n"
        "RA: 03:49:10.99\n"
        "Dec: +28:38:52.40\n"
        "Timestamp: 2026-01-02T03:04:05+00:00\n"
    )


def test_mount_slew_json(monkeypatch, capsys, backends):
    mount, _, _ = backends
    code, out, err = run_cli(
        monkeypatch,
        capsys,
        "--json",
        "mount",
        "slew",
        "--ra-deg",
        "90",
        "--dec-deg",
        "0",
    )
    payload = envelope(out)
    assert code == 0
    assert payload["command"] == "mount.slew"
    assert payload["data"] is None and payload["error"] is None
    assert mount.calls[-1][0] == "slew_to"
    assert mount.calls[-1][1] == pytest.approx(1.5707963267948966)


def test_mount_slew_human_is_silent(monkeypatch, capsys, backends):
    code, out, err = run_cli(
        monkeypatch, capsys, "mount", "slew", "--ra-deg", "10", "--dec-deg", "20"
    )
    assert code == 0
    assert out == ""
    assert err == ""


def test_mount_park_and_stop(monkeypatch, capsys, backends):
    for action in ("park", "stop"):
        code, out, err = run_cli(monkeypatch, capsys, "--json", "mount", action)
        payload = envelope(out)
        assert code == 0
        assert payload["command"] == f"mount.{action}"
        assert payload["ok"] is True


def test_mount_track_human(monkeypatch, capsys, backends):
    code, out, err = run_cli(monkeypatch, capsys, "mount", "track", "--on")
    assert code == 0
    assert out == "Tracking enabled.\n"

    code, out, err = run_cli(monkeypatch, capsys, "mount", "track", "--off")
    assert code == 0
    assert out == "Tracking disabled.\n"


def test_mount_track_json(monkeypatch, capsys, backends):
    code, out, err = run_cli(monkeypatch, capsys, "--json", "mount", "track", "--on")
    payload = envelope(out)
    assert code == 0
    assert payload["command"] == "mount.track"
    assert payload["data"] == {"tracking": True}


def test_mount_not_implemented_json(monkeypatch, capsys):
    mount = FakeMount(error=NotImplementedFeature("Mount park not implemented"))
    patch_backends(monkeypatch, mount=mount, camera=FakeCamera(), solver=FakeSolver())
    code, out, err = run_cli(monkeypatch, capsys, "--json", "mount", "park")
    payload = envelope(out)
    assert code == 2
    assert payload["command"] == "mount.park"
    assert payload["error"] == {
        "code": "not_implemented",
        "message": "Mount park not implemented",
        "details": None,
    }


def test_mount_not_implemented_human(monkeypatch, capsys):
    mount = FakeMount(error=NotImplementedFeature("Mount park not implemented"))
    patch_backends(monkeypatch, mount=mount, camera=FakeCamera(), solver=FakeSolver())
    code, out, err = run_cli(monkeypatch, capsys, "mount", "park")
    assert code == 2
    assert out == ""
    assert err == "Mount park not implemented\n"


# --------------------------------------------------------------------------
# resolve
# --------------------------------------------------------------------------


def test_resolve_json(monkeypatch, capsys):
    code, out, err = run_cli(monkeypatch, capsys, "--json", "resolve", "M110")
    payload = envelope(out)
    assert code == 0
    assert payload["command"] == "resolve"
    assert payload["ok"] is True
    assert payload["data"]["query"] == "M110"
    assert payload["data"]["matches"][0]["id"]
    assert set(payload["data"]["matches"][0]) == {
        "name",
        "id",
        "ra_deg",
        "dec_deg",
        "score",
        "reason",
    }


def test_resolve_not_found_json(monkeypatch, capsys):
    code, out, err = run_cli(monkeypatch, capsys, "--json", "resolve", "ZZZNOTATARGET")
    payload = envelope(out)
    assert code == 2
    assert payload["ok"] is False
    assert payload["error"] == {
        "code": "not_found",
        "message": "Target not found: ZZZNOTATARGET",
        "details": None,
    }


def test_resolve_not_found_human(monkeypatch, capsys):
    code, out, err = run_cli(monkeypatch, capsys, "resolve", "ZZZNOTATARGET")
    assert code == 2
    assert out == ""
    assert err == "Target not found: ZZZNOTATARGET\n"


# --------------------------------------------------------------------------
# goto compatibility alias
# --------------------------------------------------------------------------


def test_goto_requires_coordinates(monkeypatch, capsys, backends):
    code, out, err = run_cli(monkeypatch, capsys, "goto")
    assert code == 2
    assert err == "goto requires --target or both --ra-deg and --dec-deg\n"


def test_goto_target_not_found(monkeypatch, capsys, backends):
    code, out, err = run_cli(monkeypatch, capsys, "goto", "--target", "ZZZNOTATARGET")
    assert code == 2
    assert err == "Target not found: ZZZNOTATARGET\n"


def test_goto_alias_json_uses_pointing_operation(monkeypatch, capsys, backends):
    mount, _, _ = backends
    code, out, err = run_cli(
        monkeypatch, capsys, "--json", "goto", "--ra-deg", "10", "--dec-deg", "20"
    )
    payload = envelope(out)
    assert code == 0
    assert payload["command"] == "goto"
    assert set(payload["data"]) == {
        "target_ra_deg",
        "target_dec_deg",
        "command_ra_deg",
        "command_dec_deg",
        "solve",
        "final_error_arcsec",
    }
    assert payload["data"]["target_ra_deg"] == 10.0
    assert payload["data"]["target_dec_deg"] == 20.0
    assert any(call[0] == "slew_to" for call in mount.calls)


def test_goto_alias_human_success(monkeypatch, capsys, backends):
    code, out, err = run_cli(
        monkeypatch, capsys, "goto", "--ra-deg", "10", "--dec-deg", "20"
    )
    assert code == 0
    assert out.startswith("Final error: ")


def test_goto_retired_centering_flags_remain_accepted(monkeypatch, capsys, backends):
    code, out, err = run_cli(
        monkeypatch,
        capsys,
        "goto",
        "--ra-deg",
        "10",
        "--dec-deg",
        "20",
        "--tolerance-arcsec",
        "5",
        "--max-iterations",
        "9",
    )
    assert code == 0


def test_goto_alias_failure_json(monkeypatch, capsys, backends):
    _, _, solver = backends
    solver.result = solve_result(success=False)
    code, out, err = run_cli(
        monkeypatch, capsys, "--json", "goto", "--ra-deg", "10", "--dec-deg", "20"
    )
    payload = envelope(out)
    assert code == 1
    assert payload["ok"] is False
    assert payload["error"] == {
        "code": "goto_failed",
        "message": "no stars",
        "details": None,
    }


def test_goto_resolved_target_notice(monkeypatch, capsys, backends):
    code, out, err = run_cli(monkeypatch, capsys, "goto", "--target", "M110")
    assert code == 0
    assert err.startswith("Resolved 'M110' -> ")


# --------------------------------------------------------------------------
# pointing / align
# --------------------------------------------------------------------------


def test_pointing_solve_human(monkeypatch, capsys, backends):
    _service(
        monkeypatch,
        "PointingService",
        solve_current=_return(solve_result()),
    )
    code, out, err = run_cli(monkeypatch, capsys, "pointing", "solve")
    assert code == 0
    assert out == (
        "Success: True\n"
        "RA: 03:49:10.99\n"
        "Dec: +28:38:52.40\n"
        "Pixel scale: 1.25\n"
        "Rotation: 14.324°\n"
        "RMS: 0.4\n"
        "Stars: 42\n"
        "Message: solved\n"
    )


def test_pointing_solve_failure_human_has_no_raw_output(monkeypatch, capsys, backends):
    _service(
        monkeypatch,
        "PointingService",
        solve_current=_return(solve_result(success=False)),
    )
    code, out, err = run_cli(monkeypatch, capsys, "pointing", "solve")
    assert code == 1
    assert "ASTAP output" not in out
    assert "RAW SOLVER TEXT" not in out
    assert out.endswith("Message: no stars\n")


def test_pointing_solve_json(monkeypatch, capsys, backends):
    _service(
        monkeypatch,
        "PointingService",
        solve_current=_return(solve_result(success=False)),
    )
    code, out, err = run_cli(monkeypatch, capsys, "--json", "pointing", "solve")
    payload = envelope(out)
    assert code == 1
    assert payload["command"] == "pointing.solve"
    assert payload["error"] == {
        "code": "pointing_solve_failed",
        "message": "no stars",
        "details": None,
    }
    assert payload["data"]["raw_output"] == "RAW SOLVER TEXT"


def test_pointing_goto_json(monkeypatch, capsys, backends):
    _service(
        monkeypatch,
        "PointingService",
        point_to=_return(
            PointingResult(
                success=True,
                target_ra_rad=0.1,
                target_dec_rad=0.2,
                command_ra_rad=0.2,
                command_dec_rad=0.3,
                solve=solve_result(),
                final_error_arcsec=12.5,
                model_updated=False,
            )
        ),
    )
    code, out, err = run_cli(
        monkeypatch,
        capsys,
        "--json",
        "pointing",
        "goto",
        "--ra-deg",
        "11",
        "--dec-deg",
        "22",
    )
    payload = envelope(out)
    assert code == 0
    assert payload["command"] == "pointing.goto"
    assert set(payload["data"]) == {
        "target_ra_deg",
        "target_dec_deg",
        "command_ra_deg",
        "command_dec_deg",
        "solve",
        "final_error_arcsec",
    }
    assert payload["data"]["target_ra_deg"] == 11.0
    assert payload["data"]["command_ra_deg"] == pytest.approx(11.459155902616466)


def test_pointing_goto_human_failure(monkeypatch, capsys, backends):
    _service(
        monkeypatch,
        "PointingService",
        point_to=_return(
            PointingResult(
                success=False,
                target_ra_rad=0.1,
                target_dec_rad=0.2,
                command_ra_rad=0.2,
                command_dec_rad=0.3,
                solve=solve_result(success=False),
                final_error_arcsec=None,
                model_updated=False,
            )
        ),
    )
    code, out, err = run_cli(
        monkeypatch, capsys, "pointing", "goto", "--ra-deg", "11", "--dec-deg", "22"
    )
    assert code == 1
    assert out == "Pointing goto failed: no stars\n"


def test_pointing_goto_requires_coordinates(monkeypatch, capsys, backends):
    code, out, err = run_cli(monkeypatch, capsys, "pointing", "goto")
    assert code == 2
    assert err == "pointing goto requires --target or both --ra-deg and --dec-deg\n"


def test_align_alias_uses_own_command_name(monkeypatch, capsys, backends):
    _service(
        monkeypatch,
        "PointingService",
        solve_current=_return(solve_result()),
    )
    code, out, err = run_cli(monkeypatch, capsys, "--json", "align", "solve")
    payload = envelope(out)
    assert code == 0
    assert payload["command"] == "align.solve"


def test_align_goto_is_same_pointing_operation(monkeypatch, capsys, backends):
    _service(
        monkeypatch,
        "PointingService",
        point_to=_return(
            PointingResult(
                success=True,
                target_ra_rad=0.1,
                target_dec_rad=0.2,
                command_ra_rad=0.2,
                command_dec_rad=0.3,
                solve=solve_result(),
                final_error_arcsec=12.5,
                model_updated=False,
            )
        ),
    )
    code, out, err = run_cli(
        monkeypatch,
        capsys,
        "--json",
        "align",
        "goto",
        "--ra-deg",
        "11",
        "--dec-deg",
        "22",
    )
    payload = envelope(out)
    assert code == 0
    assert payload["command"] == "align.goto"
    assert payload["data"]["final_error_arcsec"] == 12.5


@pytest.mark.parametrize("mode", ["init", "sync"])
def test_pointing_alignment_phase_commands_are_removed(monkeypatch, capsys, mode):
    monkeypatch.setattr("sys.argv", ["astrolabe", "pointing", mode])
    with pytest.raises(SystemExit) as exc:
        from astrolabe.cli.main import main

        main()
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


# --------------------------------------------------------------------------
# polar
# --------------------------------------------------------------------------


def _polar_argv(*extra):
    return ("polar", "--ra-rotation-deg", "30", "--latitude-deg", "-33", *extra)


def test_polar_success_human(monkeypatch, capsys, backends):
    _service(
        monkeypatch,
        "PolarAlignService",
        run=_return(
            PolarResult(
                alt_correction_arcsec=12.0,
                az_correction_arcsec=-4.0,
                residual_arcsec=1.0,
                confidence=0.9,
                message="ok",
            )
        ),
    )
    code, out, err = run_cli(monkeypatch, capsys, *_polar_argv())
    assert code == 0
    assert out == (
        "Altitude correction (arcsec): 12.0\n"
        "Azimuth correction (arcsec): -4.0\n"
        "Residual (arcsec): 1.0\n"
        "Confidence: 0.9\n"
    )


def test_polar_failure_json(monkeypatch, capsys, backends):
    _service(
        monkeypatch,
        "PolarAlignService",
        run=_return(
            PolarResult(
                alt_correction_arcsec=None,
                az_correction_arcsec=None,
                residual_arcsec=None,
                confidence=None,
                message="not enough poses",
            )
        ),
    )
    code, out, err = run_cli(monkeypatch, capsys, "--json", *_polar_argv())
    payload = envelope(out)
    assert code == 1
    assert payload["command"] == "polar"
    assert payload["error"] == {
        "code": "polar_failed",
        "message": "not enough poses",
        "details": None,
    }


def test_polar_failure_human(monkeypatch, capsys, backends):
    _service(
        monkeypatch,
        "PolarAlignService",
        run=_return(
            PolarResult(
                alt_correction_arcsec=None,
                az_correction_arcsec=None,
                residual_arcsec=None,
                confidence=None,
                message="not enough poses",
            )
        ),
    )
    code, out, err = run_cli(monkeypatch, capsys, *_polar_argv())
    assert code == 1
    assert out == ""
    assert err == "Polar alignment failed: not enough poses\n"


def test_polar_service_error_json(monkeypatch, capsys, backends):
    _service(
        monkeypatch,
        "PolarAlignService",
        run=_raise(ServiceError("solve failed at pose 2")),
    )
    code, out, err = run_cli(monkeypatch, capsys, "--json", *_polar_argv())
    payload = envelope(out)
    assert code == 1
    assert payload["error"] == {
        "code": "service_error",
        "message": "solve failed at pose 2",
        "details": None,
    }


def test_polar_service_error_human(monkeypatch, capsys, backends):
    _service(
        monkeypatch,
        "PolarAlignService",
        run=_raise(ServiceError("solve failed at pose 2")),
    )
    code, out, err = run_cli(monkeypatch, capsys, *_polar_argv())
    assert code == 1
    assert err == "Error: solve failed at pose 2\n"


def test_polar_not_implemented(monkeypatch, capsys, backends):
    _service(
        monkeypatch,
        "PolarAlignService",
        run=_raise(NotImplementedFeature("Polar alignment not implemented")),
    )
    code, out, err = run_cli(monkeypatch, capsys, "--json", *_polar_argv())
    payload = envelope(out)
    assert code == 2
    assert payload["command"] == "polar"
    assert payload["error"]["code"] == "not_implemented"


# --------------------------------------------------------------------------
# guide
# --------------------------------------------------------------------------


def test_guide_calibrate_not_implemented_json(monkeypatch, capsys, backends):
    code, out, err = run_cli(
        monkeypatch, capsys, "--json", "guide", "calibrate", "--duration", "5"
    )
    payload = envelope(out)
    assert code == 2
    assert payload["command"] == "guide.calibrate"
    assert payload["error"] == {
        "code": "not_implemented",
        "message": "Guiding calibration not implemented",
        "details": None,
    }


def test_guide_start_not_implemented_human(monkeypatch, capsys, backends):
    code, out, err = run_cli(
        monkeypatch,
        capsys,
        "guide",
        "start",
        "--aggression",
        "0.5",
        "--min-move-arcsec",
        "1",
    )
    assert code == 2
    assert err == "Guiding start not implemented\n"


def test_guide_stop_not_implemented(monkeypatch, capsys, backends):
    code, out, err = run_cli(monkeypatch, capsys, "--json", "guide", "stop")
    payload = envelope(out)
    assert code == 2
    assert payload["command"] == "guide.stop"


def test_guide_status_not_implemented(monkeypatch, capsys, backends):
    code, out, err = run_cli(monkeypatch, capsys, "--json", "guide", "status")
    payload = envelope(out)
    assert code == 2
    assert payload["command"] == "guide.status"


def test_guide_calibrate_success_json(monkeypatch, capsys, backends):
    _service(
        monkeypatch,
        "GuidingService",
        calibrate=_return(CalibrationResult(success=True, message="done")),
    )
    code, out, err = run_cli(
        monkeypatch, capsys, "--json", "guide", "calibrate", "--duration", "5"
    )
    payload = envelope(out)
    assert code == 0
    assert payload["command"] == "guide"
    assert payload["data"] == {"success": True, "message": "done"}


def test_guide_calibrate_failure_human(monkeypatch, capsys, backends):
    _service(
        monkeypatch,
        "GuidingService",
        calibrate=_return(CalibrationResult(success=False, message="no star")),
    )
    code, out, err = run_cli(
        monkeypatch, capsys, "guide", "calibrate", "--duration", "5"
    )
    assert code == 1
    assert out == "Success: False\nMessage: no star\n"


def test_guide_status_human(monkeypatch, capsys, backends):
    _service(
        monkeypatch,
        "GuidingService",
        status=_return(
            GuidingStatus(
                running=True, rms_arcsec=0.8, star_lost=False, last_error_arcsec=0.2
            )
        ),
    )
    code, out, err = run_cli(monkeypatch, capsys, "guide", "status")
    assert code == 0
    assert out == (
        "Running: True\nRMS (arcsec): 0.8\nStar lost: False\nLast error (arcsec): 0.2\n"
    )


def test_guide_start_stop_success_json(monkeypatch, capsys, backends):
    _service(
        monkeypatch,
        "GuidingService",
        start=_return(None),
        stop=_return(None),
    )
    code, out, err = run_cli(
        monkeypatch,
        capsys,
        "--json",
        "guide",
        "start",
        "--aggression",
        "0.5",
        "--min-move-arcsec",
        "1",
    )
    payload = envelope(out)
    assert code == 0
    assert payload["command"] == "guide.start"
    assert payload["data"] is None

    code, out, err = run_cli(monkeypatch, capsys, "--json", "guide", "stop")
    payload = envelope(out)
    assert code == 0
    assert payload["command"] == "guide.stop"


# --------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------


def test_plan_conflicting_window(monkeypatch, capsys):
    code, out, err = run_cli(
        monkeypatch,
        capsys,
        "plan",
        "--start-utc",
        "2026-01-01T00:00:00Z",
        "--start-local",
        "2026-01-01T00:00:00",
    )
    assert code == 2
    assert err == "Provide either --start-utc or --start-local, not both\n"


def test_plan_conflicting_end_window(monkeypatch, capsys):
    code, out, err = run_cli(
        monkeypatch,
        capsys,
        "plan",
        "--end-utc",
        "2026-01-01T00:00:00Z",
        "--end-local",
        "2026-01-01T00:00:00",
    )
    assert code == 2
    assert err == "Provide either --end-utc or --end-local, not both\n"


def test_plan_incomplete_location(monkeypatch, capsys):
    code, out, err = run_cli(monkeypatch, capsys, "plan", "--lat", "-33")
    assert code == 2
    assert err == (
        "Both latitude and longitude are required when specifying location\n"
    )


def test_plan_json(monkeypatch, capsys):
    code, out, err = run_cli(
        monkeypatch,
        capsys,
        "--json",
        "plan",
        "--lat",
        "-33.0",
        "--lon",
        "151.0",
        "--start-utc",
        "2026-06-01T10:00:00Z",
        "--end-utc",
        "2026-06-01T14:00:00Z",
        "--limit",
        "2",
    )
    payload = envelope(out)
    assert code == 0
    assert payload["command"] == "plan"
    assert payload["ok"] is True
    assert payload["error"] is None
    assert isinstance(payload["data"], dict)


def test_plan_human(monkeypatch, capsys):
    code, out, err = run_cli(
        monkeypatch,
        capsys,
        "plan",
        "--lat",
        "-33.0",
        "--lon",
        "151.0",
        "--start-utc",
        "2026-06-01T10:00:00Z",
        "--end-utc",
        "2026-06-01T14:00:00Z",
        "--limit",
        "2",
    )
    assert code == 0
    assert out.strip() != ""


def test_plan_not_implemented(monkeypatch, capsys):
    class _Planner:
        def __init__(self, config):
            pass

        def plan(self, **kwargs):
            raise NotImplementedFeature("Planning not implemented")

    monkeypatch.setattr("astrolabe.cli.commands.Planner", _Planner)
    code, out, err = run_cli(monkeypatch, capsys, "--json", "plan")
    payload = envelope(out)
    assert code == 2
    assert payload["command"] == "plan"
    assert payload["error"]["code"] == "not_implemented"


# --------------------------------------------------------------------------
# update
# --------------------------------------------------------------------------


@pytest.fixture
def update_stubs(monkeypatch):
    monkeypatch.setattr(
        "astrolabe.cli.commands.update_catalog",
        lambda **kwargs: {
            "source": "openngc-source",
            "cache_dir": "/cache",
            "output_path": "/out/openngc.csv",
            "targets_written": 10,
        },
    )
    monkeypatch.setattr(
        "astrolabe.cli.commands.update_hipparcos",
        lambda **kwargs: {
            "source": "hip-source",
            "cache_dir": "/cache",
            "output_path": "/out/hip.csv",
            "stars_written": 20,
            "max_mag": 7.0,
        },
    )
    monkeypatch.setattr(
        "astrolabe.cli.commands.update_bsc_crosswalk",
        lambda **kwargs: {
            "source": "bsc-source",
            "hip_source": "hip-source",
            "cache_dir": "/cache",
            "output_path": "/out/bsc.csv",
            "aliases_written": 30,
        },
    )


def test_update_catalog_json(monkeypatch, capsys, update_stubs):
    code, out, err = run_cli(monkeypatch, capsys, "--json", "update", "catalog")
    payload = envelope(out)
    assert code == 0
    assert payload["command"] == "update.catalog"
    assert set(payload["data"]) == {
        "update.catalog.openngc",
        "update.catalog.hip",
        "update.catalog.bsc",
    }


def test_update_catalog_human(monkeypatch, capsys, update_stubs):
    code, out, err = run_cli(monkeypatch, capsys, "update", "catalog", "openngc")
    assert code == 0
    assert out == (
        "OpenNGC update complete.\n"
        "Source: openngc-source\n"
        "Cache: /cache\n"
        "Output: /out/openngc.csv\n"
        "Targets: 10\n"
    )


def test_update_failure_json(monkeypatch, capsys):
    def _boom(**kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("astrolabe.cli.commands.update_catalog", _boom)
    code, out, err = run_cli(
        monkeypatch, capsys, "--json", "update", "catalog", "openngc"
    )
    payload = envelope(out)
    assert code == 1
    assert payload["command"] == "update.catalog"
    assert payload["error"] == {
        "code": "update_failed",
        "message": "network down",
        "details": None,
    }


def test_update_failure_human(monkeypatch, capsys):
    def _boom(**kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("astrolabe.cli.commands.update_hipparcos", _boom)
    code, out, err = run_cli(monkeypatch, capsys, "update", "catalog", "hip")
    assert code == 1
    assert err == "Update failed: network down\n"


# --------------------------------------------------------------------------
# focus
# --------------------------------------------------------------------------


def test_focus_measure_file_not_found_json(monkeypatch, capsys, backends):
    code, out, err = run_cli(
        monkeypatch, capsys, "--json", "focus", "measure", "--in", "/nope/x.fits"
    )
    payload = envelope(out)
    assert code == 1
    assert payload["command"] == "focus.measure"
    assert payload["error"] == {
        "code": "file_not_found",
        "message": "Input file not found: /nope/x.fits",
        "details": None,
    }


def test_focus_measure_requires_exposure(monkeypatch, capsys, backends):
    code, out, err = run_cli(monkeypatch, capsys, "focus", "measure")
    assert code == 2
    assert err == (
        "Exposure is required (use --exposure or set camera.default_exposure_s).\n"
    )


def test_focus_monitor_rejects_json(monkeypatch, capsys, backends):
    code, out, err = run_cli(monkeypatch, capsys, "--json", "focus", "monitor")
    payload = envelope(out)
    assert code == 2
    assert payload["command"] == "focus.monitor"
    assert payload["error"] == {
        "code": "invalid_argument",
        "message": "focus monitor is interactive and does not support --json",
        "details": None,
    }


# --------------------------------------------------------------------------
# json-mode stdout discipline: exactly one JSON object, nothing else
# --------------------------------------------------------------------------


_JSON_INVOCATIONS = [
    ("doctor",),
    ("solve", "{fits}"),
    ("capture", "--exposure", "1"),
    ("view", "--in", "/nope/x.fits"),
    ("mount", "status"),
    ("mount", "slew", "--ra-deg", "1", "--dec-deg", "2"),
    ("mount", "park"),
    ("mount", "stop"),
    ("mount", "track", "--on"),
    ("resolve", "M110"),
    ("goto", "--ra-deg", "1", "--dec-deg", "2"),
    ("pointing", "solve"),
    ("align", "solve"),
    ("polar", "--ra-rotation-deg", "30", "--latitude-deg", "-33"),
    ("guide", "calibrate", "--duration", "1"),
    ("guide", "start", "--aggression", "0.5", "--min-move-arcsec", "1"),
    ("guide", "stop"),
    ("guide", "status"),
    ("plan", "--lat", "-33.0", "--lon", "151.0"),
    ("focus", "measure", "--in", "/nope/x.fits"),
    ("focus", "monitor"),
]


@pytest.mark.parametrize("argv", _JSON_INVOCATIONS, ids=lambda a: ".".join(a[:2]))
def test_json_mode_emits_single_envelope(monkeypatch, capsys, backends, tmp_path, argv):
    fits = tmp_path / "frame.fits"
    fits.write_text("x")
    argv = tuple(part.format(fits=fits) for part in argv)
    monkeypatch.setattr(
        "astrolabe.cli.commands.socket.create_connection",
        lambda *a, **k: _Closable(),
    )
    code, out, err = run_cli(monkeypatch, capsys, "--json", *argv)
    payload = json.loads(out)
    assert set(payload) == {"ok", "command", "timestamp_utc", "data", "error"}
    assert code in (0, 1, 2)
    assert (payload["error"] is None) == payload["ok"]


# --------------------------------------------------------------------------
# solve on a real solver failure exercised through the not-found guard only;
# unknown-action guards below are reachable only by calling handlers directly.
# --------------------------------------------------------------------------


def test_unknown_mount_action(monkeypatch, capsys, backends):
    from types import SimpleNamespace

    from astrolabe.cli.commands import run_mount

    args = SimpleNamespace(
        action="bogus", json=False, log_level=None, config=None, dry_run=False
    )
    assert run_mount(args) == 2
    assert capsys.readouterr().err == "Unknown mount action.\n"


def test_unknown_guide_action(monkeypatch, capsys, backends):
    from types import SimpleNamespace

    from astrolabe.cli.commands import run_guide

    args = SimpleNamespace(
        action="bogus", json=False, log_level=None, config=None, dry_run=False
    )
    assert run_guide(args) == 2
    assert capsys.readouterr().err == "Unknown guiding action.\n"


def test_unknown_pointing_mode(monkeypatch, capsys, backends):
    from types import SimpleNamespace

    from astrolabe.cli.commands import run_align

    args = SimpleNamespace(
        command="pointing",
        mode="bogus",
        json=False,
        log_level=None,
        config=None,
        dry_run=False,
    )
    assert run_align(args) == 2
    assert capsys.readouterr().err == "Unknown pointing mode.\n"


def test_unknown_update_dataset(monkeypatch, capsys):
    from types import SimpleNamespace

    from astrolabe.cli.commands import run_update

    args = SimpleNamespace(
        dataset="bogus", json=False, log_level=None, config=None, dry_run=False
    )
    assert run_update(args) == 2
    assert capsys.readouterr().err == "Unknown update dataset.\n"


def test_unknown_focus_action(monkeypatch, capsys, backends):
    from types import SimpleNamespace

    from astrolabe.cli.focus import run_focus

    args = SimpleNamespace(
        action="bogus", json=True, log_level=None, config=None, dry_run=False
    )
    assert run_focus(args) == 2
    payload = envelope(capsys.readouterr().out)
    assert payload["command"] == "focus"
    assert payload["error"]["code"] == "invalid_argument"


# --------------------------------------------------------------------------
# dry-run notices (contract-adjacent stderr)
# --------------------------------------------------------------------------


# (argv, complete expected stderr). The dry-run notice is contract-adjacent, so
# the whole of stderr is pinned, not merely the presence of the notice.
_DRY_RUN_NOTICES = [
    (
        ("solve", "/nope/x.fits"),
        "--dry-run has no effect for solve.\nInput file not found: /nope/x.fits\n",
    ),
    (("capture", "--exposure", "1"), "--dry-run has no effect for capture.\n"),
    (
        ("view", "--in", "/nope/x.fits"),
        "--dry-run has no effect for view.\nInput file not found: /nope/x.fits\n",
    ),
    (("mount", "status"), "--dry-run has no effect for mount.\n"),
    (("resolve", "M110"), "--dry-run has no effect for resolve.\n"),
    (
        ("goto", "--ra-deg", "1", "--dec-deg", "2"),
        "--dry-run has no effect for goto.\n",
    ),
    (("pointing", "solve"), "--dry-run has no effect for pointing.\n"),
    (
        ("polar", "--ra-rotation-deg", "30", "--latitude-deg", "-33"),
        "--dry-run has no effect for polar.\n"
        "Polar alignment failed: Circle fit failed: Two points are identical\n",
    ),
    (
        ("guide", "stop"),
        "--dry-run has no effect for guide.\nGuiding stop not implemented\n",
    ),
    (
        ("plan",),
        "--dry-run has no effect for plan.\nObserver location is required (lat/lon)\n",
    ),
    (
        ("focus", "measure", "--in", "/nope/x.fits"),
        "--dry-run has no effect for focus measurement.\n"
        "Input file not found: /nope/x.fits\n",
    ),
]


@pytest.mark.parametrize("argv,notice", _DRY_RUN_NOTICES, ids=lambda v: str(v)[:30])
def test_dry_run_notice(monkeypatch, capsys, backends, argv, notice):
    """The notice is the whole of stderr for these invocations."""
    code, out, err = run_cli(monkeypatch, capsys, "--dry-run", *argv)
    assert err == notice


def test_dry_run_notice_update(monkeypatch, capsys, update_stubs):
    code, out, err = run_cli(
        monkeypatch, capsys, "--dry-run", "update", "catalog", "openngc"
    )
    assert code == 0
    assert err == "--dry-run has no effect for update.\n"


def test_dry_run_notice_focus_monitor(monkeypatch, capsys, backends):
    code, out, err = run_cli(
        monkeypatch, capsys, "--dry-run", "focus", "monitor", "--frames", "0"
    )
    assert code == 2
    assert err == (
        "--dry-run has no effect for focus monitoring.\n--frames must be at least 1\n"
    )
