import datetime
from pathlib import Path

from astrolabe.pointing.model import PointingModel


def test_pointing_model_update():
    model = PointingModel()
    model.update(0.1, -0.2, weight=0.5)
    assert model.b_alpha_rad == 0.05
    assert model.b_delta_rad == -0.1
    assert model.num_samples == 1
    assert model.last_update_utc is not None


def test_pointing_model_round_trip(tmp_path):
    path = tmp_path / "pointing.json"
    model = PointingModel(
        b_alpha_rad=0.01,
        b_delta_rad=-0.02,
        num_samples=5,
        last_update_utc=datetime.datetime(2026, 2, 22, tzinfo=datetime.timezone.utc),
    )
    model.save(path)

    loaded = PointingModel.load(path)
    assert loaded.b_alpha_rad == model.b_alpha_rad
    assert loaded.b_delta_rad == model.b_delta_rad
    assert loaded.num_samples == model.num_samples
    assert loaded.last_update_utc == model.last_update_utc


def test_pointing_model_missing_file(tmp_path):
    path = tmp_path / "missing.json"
    model = PointingModel.load(path)
    assert model.num_samples == 0
