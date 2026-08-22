"""CLI composition tests for explicit pointing-model persistence."""

from __future__ import annotations

from astrolabe.pointing import (
    PointingModel,
    PointingResult,
    load_pointing_model,
    save_pointing_model,
)
from golden import (
    FakeCamera,
    FakeMount,
    FakeSolver,
    patch_backends,
    run_cli,
    solve_result,
)


def _install_backends(monkeypatch) -> None:
    patch_backends(
        monkeypatch,
        mount=FakeMount(),
        camera=FakeCamera(),
        solver=FakeSolver(),
    )


def test_pointing_goto_loads_and_saves_persisted_model(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    model_path = tmp_path / ".astrolabe" / "pointing.json"
    save_pointing_model(
        PointingModel(b_alpha_rad=0.125, b_delta_rad=-0.25, num_samples=3),
        model_path,
    )
    _install_backends(monkeypatch)

    class _PointingService:
        def __init__(self, mount, camera, solver, model: PointingModel):
            assert model.b_alpha_rad == 0.125
            assert model.b_delta_rad == -0.25
            assert model.num_samples == 3
            self.model = model

        def point_to(self, ra_rad, dec_rad, exposure_s=None):
            self.model.b_alpha_rad = 0.5
            self.model.b_delta_rad = 0.75
            self.model.num_samples = 4
            solve = solve_result()
            return PointingResult(
                success=True,
                target_ra_rad=ra_rad,
                target_dec_rad=dec_rad,
                command_ra_rad=ra_rad,
                command_dec_rad=dec_rad,
                solve=solve,
                final_error_arcsec=12.0,
                model_updated=True,
            )

    monkeypatch.setattr("astrolabe.cli.commands.PointingService", _PointingService)

    code, out, err = run_cli(
        monkeypatch,
        capsys,
        "pointing",
        "goto",
        "--ra-deg",
        "11",
        "--dec-deg",
        "22",
    )

    assert code == 0
    persisted = load_pointing_model(model_path)
    assert persisted.b_alpha_rad == 0.5
    assert persisted.b_delta_rad == 0.75
    assert persisted.num_samples == 4


def test_pointing_goto_does_not_save_rejected_observation(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.setenv("HOME", str(tmp_path))
    model_path = tmp_path / ".astrolabe" / "pointing.json"
    original = PointingModel(b_alpha_rad=0.125, b_delta_rad=-0.25, num_samples=3)
    save_pointing_model(original, model_path)
    _install_backends(monkeypatch)

    class _PointingService:
        def __init__(self, mount, camera, solver, model: PointingModel):
            self.model = model

        def point_to(self, ra_rad, dec_rad, exposure_s=None):
            solve = solve_result(success=False)
            return PointingResult(
                success=False,
                target_ra_rad=ra_rad,
                target_dec_rad=dec_rad,
                command_ra_rad=ra_rad,
                command_dec_rad=dec_rad,
                solve=solve,
                final_error_arcsec=None,
                model_updated=False,
            )

    monkeypatch.setattr("astrolabe.cli.commands.PointingService", _PointingService)

    code, out, err = run_cli(
        monkeypatch,
        capsys,
        "pointing",
        "goto",
        "--ra-deg",
        "11",
        "--dec-deg",
        "22",
    )

    assert code == 1
    persisted = load_pointing_model(model_path)
    assert persisted.b_alpha_rad == original.b_alpha_rad
    assert persisted.b_delta_rad == original.b_delta_rad
    assert persisted.num_samples == original.num_samples


def test_pointing_solve_does_not_read_persisted_model(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    model_path = tmp_path / ".astrolabe" / "pointing.json"
    model_path.parent.mkdir(parents=True)
    model_path.write_text("not valid json", encoding="utf-8")
    _install_backends(monkeypatch)

    class _PointingService:
        def __init__(self, mount, camera, solver, model: PointingModel):
            assert model == PointingModel()

        def solve_current(self, exposure_s=None, *, use_mount_hints=True):
            return solve_result()

    monkeypatch.setattr("astrolabe.cli.commands.PointingService", _PointingService)

    code, out, err = run_cli(monkeypatch, capsys, "pointing", "solve")

    assert code == 0
