import datetime

from astrolabe.camera import Image
from astrolabe.camera.types import Image as CameraImage
from astrolabe.solver.types import Image as LegacySolverImage


def test_image_is_camera_owned_public_contract():
    timestamp = datetime.datetime(2026, 8, 21, tzinfo=datetime.timezone.utc)
    image = Image(
        data="frame.fits",
        width_px=640,
        height_px=480,
        timestamp_utc=timestamp,
        exposure_s=1.5,
        metadata={"source": "test"},
    )

    assert Image is CameraImage
    assert Image.__module__ == "astrolabe.camera.types"
    assert LegacySolverImage is Image
    assert image.data == "frame.fits"
    assert image.width_px == 640
    assert image.height_px == 480
    assert image.timestamp_utc == timestamp
    assert image.exposure_s == 1.5
    assert image.metadata == {"source": "test"}
