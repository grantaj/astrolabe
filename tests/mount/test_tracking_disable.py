from types import SimpleNamespace
from unittest.mock import patch

import pytest

from astrolabe.errors import BackendError
from astrolabe.mount.indi import IndiMountBackend


def _mount() -> IndiMountBackend:
    mount = IndiMountBackend(host="127.0.0.1", port=7624, device="Test Mount")
    mount._connected = True
    return mount


def test_tracking_disable_requires_track_off_switch():
    mount = _mount()

    with (
        patch(
            "astrolabe.mount.indi.IndiClient.has_prop",
            return_value=False,
        ),
        patch("astrolabe.mount.indi.IndiClient.setprop") as setprop,
        pytest.raises(BackendError, match="TRACK_OFF is unavailable"),
    ):
        mount.set_tracking(False)

    setprop.assert_not_called()


def test_tracking_disable_waits_for_reported_off_state():
    mount = _mount()

    with (
        patch(
            "astrolabe.mount.indi.IndiClient.has_prop",
            return_value=True,
        ),
        patch("astrolabe.mount.indi.IndiClient.setprop") as setprop,
        patch.object(
            mount,
            "get_state",
            side_effect=[
                SimpleNamespace(tracking=True),
                SimpleNamespace(tracking=False),
            ],
        ) as get_state,
        patch("astrolabe.mount.indi.time.sleep") as sleep,
    ):
        mount.set_tracking(False)

    setprop.assert_called_once_with(
        "Test Mount.TELESCOPE_TRACK_STATE.TRACK_OFF",
        "On",
        kind="s",
        soft=False,
    )
    assert get_state.call_count == 2
    sleep.assert_called_once()


def test_tracking_disable_fails_if_reported_state_never_changes():
    mount = _mount()

    with (
        patch(
            "astrolabe.mount.indi.IndiClient.has_prop",
            return_value=True,
        ),
        patch("astrolabe.mount.indi.IndiClient.setprop"),
        patch.object(
            mount,
            "get_state",
            return_value=SimpleNamespace(tracking=True),
        ),
        patch("astrolabe.mount.indi.time.monotonic", side_effect=[0.0, 2.0]),
        patch("astrolabe.mount.indi.time.sleep") as sleep,
        pytest.raises(BackendError, match="did not report tracking disabled"),
    ):
        mount.set_tracking(False)

    sleep.assert_not_called()
