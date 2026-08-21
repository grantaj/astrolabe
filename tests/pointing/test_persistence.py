import datetime

from astrolabe.pointing import (
    PointingModel,
    default_model_path,
    load_pointing_model,
    save_pointing_model,
)


def test_pointing_model_round_trip(tmp_path):
    path = tmp_path / "pointing.json"
    model = PointingModel(
        b_alpha_rad=0.01,
        b_delta_rad=-0.02,
        num_samples=5,
        last_update_utc=datetime.datetime(2026, 2, 22, tzinfo=datetime.timezone.utc),
    )
    save_pointing_model(model, path)

    loaded = load_pointing_model(path)
    assert loaded.b_alpha_rad == model.b_alpha_rad
    assert loaded.b_delta_rad == model.b_delta_rad
    assert loaded.num_samples == model.num_samples
    assert loaded.last_update_utc == model.last_update_utc


def test_pointing_model_missing_file(tmp_path):
    path = tmp_path / "missing.json"
    model = load_pointing_model(path)
    assert model.num_samples == 0


def test_default_model_path_is_resolved_at_composition_time(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_model_path() == tmp_path / ".astrolabe" / "pointing.json"
