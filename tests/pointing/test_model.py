from astrolabe.pointing import PointingModel


def test_pointing_model_update():
    model = PointingModel()
    model.update(0.1, -0.2, weight=0.5)
    assert model.b_alpha_rad == 0.05
    assert model.b_delta_rad == -0.1
    assert model.num_samples == 1
    assert model.last_update_utc is not None


def test_pointing_model_has_no_persistence_api():
    model = PointingModel()
    assert not hasattr(model, "save")
    assert not hasattr(PointingModel, "load")
