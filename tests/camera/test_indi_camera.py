from unittest.mock import patch

import pytest

from astrolabe.camera.indi import IndiCameraBackend


@pytest.fixture
def camera(tmp_path):
    return IndiCameraBackend(
        host="127.0.0.1",
        port=7624,
        device="CCD Simulator",
        output_dir=tmp_path,
        output_prefix="astrolabe_capture_",
        use_guider_exposure=False,
    )


def test_connect_sets_upload_options(camera):
    with (
        patch("astrolabe.camera.indi.IndiClient.setprop") as mock_setprop,
        patch("astrolabe.camera.indi.IndiClient.wait_for_device"),
        patch("astrolabe.camera.indi.IndiClient.has_prop", return_value=True),
    ):
        camera.connect()
        props = [c.args[0] for c in mock_setprop.call_args_list]
        assert any("UPLOAD_MODE.UPLOAD_LOCAL" in prop for prop in props)
        assert any("UPLOAD_SETTINGS.UPLOAD_DIR" in prop for prop in props)
        assert any("UPLOAD_SETTINGS.UPLOAD_PREFIX" in prop for prop in props)


def test_capture_sets_gain_bin_roi_and_exposure(camera, tmp_path):
    camera._gain_prop = "CCD_GAIN.GAIN"
    camera._connected = True
    old_path = tmp_path / "old.fits"
    new_path = tmp_path / "new.fits"
    old_path.write_text("old")
    new_path.write_text("new")

    with (
        patch(
            "astrolabe.camera.indi.IndiClient.getprop_value",
            side_effect=[str(old_path), str(new_path)],
        ),
        patch("astrolabe.camera.indi.IndiClient.setprop") as mock_setprop,
        patch("astrolabe.camera.indi.IndiClient.has_prop", return_value=True),
    ):
        image = camera.capture(
            exposure_s=2.5,
            gain=10.0,
            binning=2,
            roi=(1, 2, 640, 480),
        )

    assert image.data == str(new_path)
    assert image.exposure_s == 2.5
    assert image.timestamp_utc.tzinfo is not None

    calls = [(c.args[0], c.args[1]) for c in mock_setprop.call_args_list]
    assert any(prop.endswith("CCD_GAIN.GAIN") and val == "10.0" for prop, val in calls)
    assert any(
        prop.endswith("CCD_BINNING.HOR_BIN") and val == "2" for prop, val in calls
    )
    assert any(
        prop.endswith("CCD_BINNING.VER_BIN") and val == "2" for prop, val in calls
    )
    assert any(prop.endswith("CCD_FRAME.X") and val == "1" for prop, val in calls)
    assert any(prop.endswith("CCD_FRAME.Y") and val == "2" for prop, val in calls)
    assert any(prop.endswith("CCD_FRAME.WIDTH") and val == "640" for prop, val in calls)
    assert any(
        prop.endswith("CCD_FRAME.HEIGHT") and val == "480" for prop, val in calls
    )
    assert any(
        prop.endswith("CCD_EXPOSURE.CCD_EXPOSURE_VALUE") and val == "2.5"
        for prop, val in calls
    )


def test_capture_uses_guider_exposure(camera, tmp_path):
    camera.use_guider_exposure = True
    camera._gain_prop = "CCD_GAIN.GAIN"
    camera._connected = True
    old_path = tmp_path / "old.fits"
    new_path = tmp_path / "new.fits"
    old_path.write_text("old")
    new_path.write_text("new")

    with (
        patch(
            "astrolabe.camera.indi.IndiClient.getprop_value",
            side_effect=[str(old_path), str(new_path)],
        ),
        patch("astrolabe.camera.indi.IndiClient.setprop") as mock_setprop,
        patch("astrolabe.camera.indi.IndiClient.has_prop", return_value=True),
    ):
        camera.capture(exposure_s=1.0)

    calls = [(c.args[0], c.args[1]) for c in mock_setprop.call_args_list]
    assert any(
        prop.endswith("GUIDER_EXPOSURE.GUIDER_EXPOSURE_VALUE") and val == "1.0"
        for prop, val in calls
    )
