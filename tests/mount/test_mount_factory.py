from unittest.mock import patch

from astrolabe.config import Config
from astrolabe.mount import get_mount_backend
from astrolabe.mount.indi import IndiMountBackend


def test_indi_mount_backend_takes_explicit_mount_inputs():
    with patch("astrolabe.mount.indi.IndiClient") as client_cls:
        mount = IndiMountBackend(
            host="indi.example",
            port=8765,
            device="Test Mount",
        )

    client_cls.assert_called_once_with("indi.example", 8765)
    assert mount.host == "indi.example"
    assert mount.port == 8765
    assert mount.device == "Test Mount"
    assert not hasattr(mount, "_config")


def test_get_mount_backend_is_config_composition_point():
    config = Config(
        {
            "indi": {"host": "indi.example", "port": 8765},
            "mount": {"backend": "indi", "device": "Test Mount"},
        }
    )

    with patch("astrolabe.mount.IndiMountBackend") as backend_cls:
        backend = get_mount_backend(config)

    backend_cls.assert_called_once_with(
        host="indi.example",
        port=8765,
        device="Test Mount",
    )
    assert backend is backend_cls.return_value
