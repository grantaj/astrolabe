import math
import shutil
import time
from unittest.mock import patch

import pytest

from astrolabe.mount.indi import IndiMountBackend, _hours_to_rad, _degrees_to_rad
from astrolabe.errors import BackendError
from astrolabe.config import Config


@pytest.fixture
def config():
    return Config(
        {
            "indi": {"host": "127.0.0.1", "port": 7624},
            "mount": {"device": "Telescope Simulator"},
        }
    )


@pytest.fixture
def mount(config):
    return IndiMountBackend(config)


def test_connect_waits_for_device(mount):
    with (
        patch("astrolabe.mount.indi.IndiClient.wait_for_device") as mock_wait,
        patch("astrolabe.mount.indi.IndiClient.setprop") as mock_setprop,
    ):
        mount.connect()
        mock_wait.assert_called_once_with("Telescope Simulator", timeout_s=10.0)
        mock_setprop.assert_called_once_with(
            "Telescope Simulator.CONNECTION.CONNECT", "On", soft=False
        )
        assert mount.is_connected()


def test_disconnect(mount):
    mount._connected = True
    with patch("astrolabe.mount.indi.IndiClient.setprop") as mock_setprop:
        mount.disconnect()
        mock_setprop.assert_called_once_with(
            "Telescope Simulator.CONNECTION.DISCONNECT", "On", soft=True
        )
        assert not mount.is_connected()


def test_slew_to_jnow(mount):
    mount._connected = True
    with (
        patch("astrolabe.mount.indi.IndiClient.has_prop") as mock_has_prop,
        patch("astrolabe.mount.indi.IndiClient.setprop") as mock_setprop,
        patch("astrolabe.mount.indi.IndiClient.setprop_multi") as mock_setprop_multi,
        patch("astrolabe.mount.indi.IndiClient.setprop_vector") as mock_setprop_vector,
        patch("astrolabe.mount.indi.icrs_to_jnow") as mock_icrs,
    ):

        def has_prop_mock(prop):
            if "EQUATORIAL_EOD_COORD" in prop:
                return True
            if "ON_COORD_SET" in prop:
                return True
            return False

        mock_has_prop.side_effect = has_prop_mock
        mock_icrs.return_value = (math.pi / 2, math.pi / 4)  # 6h, 45deg

        mount.slew_to(math.pi / 2, math.pi / 4)

        multi_calls = [c.args[0] for c in mock_setprop_multi.call_args_list]
        vector_calls = [c.args for c in mock_setprop_vector.call_args_list]
        assert {
            "Telescope Simulator.ON_COORD_SET.TRACK": "Off",
            "Telescope Simulator.ON_COORD_SET.SLEW": "On",
            "Telescope Simulator.ON_COORD_SET.SYNC": "Off",
        } in multi_calls
        assert (
            "Telescope Simulator",
            "EQUATORIAL_EOD_COORD",
            {"RA": str(6.0), "DEC": str(45.0)},
        ) in vector_calls
        assert {
            "Telescope Simulator.EQUATORIAL_EOD_COORD.RA": str(6.0),
            "Telescope Simulator.EQUATORIAL_EOD_COORD.DEC": str(45.0),
        } in multi_calls


def test_slew_to_j2000(mount):
    mount._connected = True
    with (
        patch("astrolabe.mount.indi.IndiClient.has_prop") as mock_has_prop,
        patch("astrolabe.mount.indi.IndiClient.setprop") as mock_setprop,
        patch("astrolabe.mount.indi.IndiClient.setprop_multi") as mock_setprop_multi,
        patch("astrolabe.mount.indi.IndiClient.setprop_vector") as mock_setprop_vector,
    ):

        def has_prop_mock(prop):
            if "EQUATORIAL_COORD" in prop and "EOD" not in prop:
                return True
            if "ON_COORD_SET" in prop:
                return True
            return False

        mock_has_prop.side_effect = has_prop_mock

        mount.slew_to(math.pi / 2, math.pi / 4)

        vector_calls = [c.args for c in mock_setprop_vector.call_args_list]
        assert (
            "Telescope Simulator",
            "EQUATORIAL_COORD",
            {"RA": str(6.0), "DEC": str(45.0)},
        ) in vector_calls


def test_sync_jnow(mount):
    mount._connected = True
    with (
        patch("astrolabe.mount.indi.IndiClient.has_prop") as mock_has_prop,
        patch("astrolabe.mount.indi.IndiClient.setprop") as mock_setprop,
        patch("astrolabe.mount.indi.IndiClient.setprop_multi") as mock_setprop_multi,
        patch("astrolabe.mount.indi.IndiClient.setprop_vector") as mock_setprop_vector,
        patch("astrolabe.mount.indi.icrs_to_jnow") as mock_icrs,
    ):

        def has_prop_mock(prop):
            if "EQUATORIAL_EOD_COORD" in prop:
                return True
            if "ON_COORD_SET" in prop:
                return True
            return False

        mock_has_prop.side_effect = has_prop_mock
        mock_icrs.return_value = (math.pi / 2, math.pi / 4)

        mount.sync(math.pi / 2, math.pi / 4)

        multi_calls = [c.args[0] for c in mock_setprop_multi.call_args_list]
        vector_calls = [c.args for c in mock_setprop_vector.call_args_list]
        assert {
            "Telescope Simulator.ON_COORD_SET.TRACK": "Off",
            "Telescope Simulator.ON_COORD_SET.SLEW": "Off",
            "Telescope Simulator.ON_COORD_SET.SYNC": "On",
        } in multi_calls
        assert (
            "Telescope Simulator",
            "EQUATORIAL_EOD_COORD",
            {"RA": str(6.0), "DEC": str(45.0)},
        ) in vector_calls


def test_sync_j2000(mount):
    mount._connected = True
    with (
        patch("astrolabe.mount.indi.IndiClient.has_prop") as mock_has_prop,
        patch("astrolabe.mount.indi.IndiClient.setprop") as mock_setprop,
        patch("astrolabe.mount.indi.IndiClient.setprop_multi") as mock_setprop_multi,
        patch("astrolabe.mount.indi.IndiClient.setprop_vector") as mock_setprop_vector,
    ):

        def has_prop_mock(prop):
            if "EQUATORIAL_COORD" in prop and "EOD" not in prop:
                return True
            if "ON_COORD_SET" in prop:
                return True
            return False

        mock_has_prop.side_effect = has_prop_mock

        mount.sync(math.pi / 2, math.pi / 4)

        multi_calls = [c.args[0] for c in mock_setprop_multi.call_args_list]
        vector_calls = [c.args for c in mock_setprop_vector.call_args_list]
        assert {
            "Telescope Simulator.ON_COORD_SET.TRACK": "Off",
            "Telescope Simulator.ON_COORD_SET.SLEW": "Off",
            "Telescope Simulator.ON_COORD_SET.SYNC": "On",
        } in multi_calls
        assert (
            "Telescope Simulator",
            "EQUATORIAL_COORD",
            {"RA": str(6.0), "DEC": str(45.0)},
        ) in vector_calls


def test_slew_to_wraps_ra_j2000(mount):
    mount._connected = True
    with (
        patch("astrolabe.mount.indi.IndiClient.has_prop") as mock_has_prop,
        patch("astrolabe.mount.indi.IndiClient.setprop") as mock_setprop,
        patch("astrolabe.mount.indi.IndiClient.setprop_multi") as mock_setprop_multi,
        patch("astrolabe.mount.indi.IndiClient.setprop_vector") as mock_setprop_vector,
    ):

        def has_prop_mock(prop):
            if "EQUATORIAL_COORD" in prop and "EOD" not in prop:
                return True
            if "ON_COORD_SET" in prop:
                return True
            return False

        mock_has_prop.side_effect = has_prop_mock

        mount.slew_to(-math.pi / 2, math.pi / 4)

        vector_calls = [c.args for c in mock_setprop_vector.call_args_list]
        # -pi/2 wraps to 3pi/2 => 18h
        assert (
            "Telescope Simulator",
            "EQUATORIAL_COORD",
            {"RA": str(18.0), "DEC": str(45.0)},
        ) in vector_calls


def test_slew_to_wraps_ra_jnow(mount):
    mount._connected = True
    with (
        patch("astrolabe.mount.indi.IndiClient.has_prop") as mock_has_prop,
        patch("astrolabe.mount.indi.IndiClient.setprop") as mock_setprop,
        patch("astrolabe.mount.indi.IndiClient.setprop_multi") as mock_setprop_multi,
        patch("astrolabe.mount.indi.IndiClient.setprop_vector") as mock_setprop_vector,
        patch("astrolabe.mount.indi.icrs_to_jnow") as mock_icrs,
    ):

        def has_prop_mock(prop):
            if "EQUATORIAL_EOD_COORD" in prop:
                return True
            if "ON_COORD_SET" in prop:
                return True
            return False

        mock_has_prop.side_effect = has_prop_mock
        mock_icrs.return_value = (-math.pi / 2, math.pi / 4)  # -6h wraps to 18h

        mount.slew_to(math.pi / 2, math.pi / 4)

        vector_calls = [c.args for c in mock_setprop_vector.call_args_list]
        assert (
            "Telescope Simulator",
            "EQUATORIAL_EOD_COORD",
            {"RA": str(18.0), "DEC": str(45.0)},
        ) in vector_calls


def test_get_state_jnow(mount):
    mount._connected = True
    with (
        patch("astrolabe.mount.indi.IndiClient.has_prop") as mock_has_prop,
        patch("astrolabe.mount.indi.IndiClient.getprop_value") as mock_getprop,
        patch("astrolabe.mount.indi.IndiClient.getprop_state") as mock_getprop_state,
        patch("astrolabe.mount.indi.jnow_to_icrs") as mock_jnow_to_icrs,
    ):

        def has_prop_mock(prop):
            if "EQUATORIAL_EOD_COORD" in prop:
                return True
            if "TELESCOPE_TRACK_STATE.TRACK_ON" in prop:
                return True
            return False

        mock_has_prop.side_effect = has_prop_mock

        def getprop_mock(prop):
            if "EQUATORIAL_EOD_COORD.RA" in prop:
                return "6.0"
            if "EQUATORIAL_EOD_COORD.DEC" in prop:
                return "45.0"
            if "TRACK_ON" in prop:
                return "On"
            return ""

        mock_getprop.side_effect = getprop_mock
        mock_getprop_state.return_value = "Ok"
        mock_jnow_to_icrs.return_value = (math.pi / 2, math.pi / 4)

        state = mount.get_state()

        assert state.connected is True
        assert state.tracking is True
        assert math.isclose(state.ra_rad, math.pi / 2)
        assert math.isclose(state.dec_rad, math.pi / 4)
        assert state.slewing is False
        mock_getprop_state.assert_called_once_with(
            "Telescope Simulator.EQUATORIAL_EOD_COORD"
        )


def test_get_state_detects_slewing(mount):
    mount._connected = True
    with (
        patch("astrolabe.mount.indi.IndiClient.has_prop") as mock_has_prop,
        patch("astrolabe.mount.indi.IndiClient.getprop_value") as mock_getprop,
        patch("astrolabe.mount.indi.IndiClient.getprop_state") as mock_getprop_state,
        patch("astrolabe.mount.indi.jnow_to_icrs") as mock_jnow_to_icrs,
    ):

        def has_prop_mock(prop):
            if "EQUATORIAL_EOD_COORD" in prop:
                return True
            return False

        mock_has_prop.side_effect = has_prop_mock

        def getprop_mock(prop):
            if "EQUATORIAL_EOD_COORD.RA" in prop:
                return "6.0"
            if "EQUATORIAL_EOD_COORD.DEC" in prop:
                return "45.0"
            return ""

        mock_getprop.side_effect = getprop_mock
        mock_getprop_state.return_value = "Busy"
        mock_jnow_to_icrs.return_value = (math.pi / 2, math.pi / 4)

        state = mount.get_state()

        assert state.slewing is True
        mock_getprop_state.assert_called_once_with(
            "Telescope Simulator.EQUATORIAL_EOD_COORD"
        )


def test_get_state_j2000(mount):
    mount._connected = True
    with (
        patch("astrolabe.mount.indi.IndiClient.has_prop") as mock_has_prop,
        patch("astrolabe.mount.indi.IndiClient.getprop_value") as mock_getprop,
        patch("astrolabe.mount.indi.IndiClient.getprop_state") as mock_getprop_state,
    ):

        def has_prop_mock(prop):
            if "EQUATORIAL_EOD_COORD" in prop:
                return False
            if "EQUATORIAL_COORD" in prop:
                return True
            if "TELESCOPE_TRACK_STATE.TRACK_ON" in prop:
                return True
            return False

        mock_has_prop.side_effect = has_prop_mock

        def getprop_mock(prop):
            if "EQUATORIAL_COORD.RA" in prop:
                return "1.0"
            if "EQUATORIAL_COORD.DEC" in prop:
                return "2.0"
            if "TRACK_ON" in prop:
                return "On"
            return ""

        mock_getprop.side_effect = getprop_mock
        mock_getprop_state.return_value = "Ok"

        state = mount.get_state()

        assert state.connected is True
        assert state.tracking is True
        assert math.isclose(state.ra_rad, _hours_to_rad(1.0))
        assert math.isclose(state.dec_rad, _degrees_to_rad(2.0))
        assert state.slewing is False
        mock_getprop_state.assert_called_once_with(
            "Telescope Simulator.EQUATORIAL_COORD"
        )


def test_set_tracking_enables(mount):
    mount._connected = True
    with (
        patch("astrolabe.mount.indi.IndiClient.has_prop") as mock_has_prop,
        patch("astrolabe.mount.indi.IndiClient.setprop") as mock_setprop,
    ):
        mock_has_prop.return_value = True
        mount.set_tracking(True)

        calls = [(c.args[0], c.args[1]) for c in mock_setprop.call_args_list]
        assert ("Telescope Simulator.TELESCOPE_TRACK_STATE.TRACK_ON", "On") in calls


def test_set_tracking_disables(mount):
    mount._connected = True
    with (
        patch("astrolabe.mount.indi.IndiClient.has_prop") as mock_has_prop,
        patch("astrolabe.mount.indi.IndiClient.setprop") as mock_setprop,
    ):
        mock_has_prop.return_value = True
        mount.set_tracking(False)

        calls = [(c.args[0], c.args[1]) for c in mock_setprop.call_args_list]
        assert ("Telescope Simulator.TELESCOPE_TRACK_STATE.TRACK_OFF", "On") in calls


def test_stop(mount):
    mount._connected = True
    with (
        patch("astrolabe.mount.indi.IndiClient.has_prop") as mock_has_prop,
        patch("astrolabe.mount.indi.IndiClient.setprop") as mock_setprop,
    ):
        mock_has_prop.return_value = True
        mount.stop()

        mock_setprop.assert_called_once_with(
            "Telescope Simulator.TELESCOPE_ABORT_MOTION.ABORT", "On", soft=True
        )


def test_park(mount):
    mount._connected = True
    with (
        patch("astrolabe.mount.indi.IndiClient.has_prop") as mock_has_prop,
        patch("astrolabe.mount.indi.IndiClient.setprop") as mock_setprop,
    ):
        mock_has_prop.return_value = True
        mount.park()

        mock_setprop.assert_called_once_with(
            "Telescope Simulator.TELESCOPE_PARK.PARK", "On", soft=True
        )


def test_pulse_guide_positive_ra(mount):
    mount._connected = True
    with (
        patch("astrolabe.mount.indi.IndiClient.has_prop") as mock_has_prop,
        patch("astrolabe.mount.indi.IndiClient.setprop") as mock_setprop,
    ):

        def has_prop_mock(prop):
            if "TIMED_GUIDE" in prop:
                return True
            return False

        mock_has_prop.side_effect = has_prop_mock
        mount.pulse_guide(100.0, 0)

        calls = [(c.args[0], c.args[1]) for c in mock_setprop.call_args_list]
        assert (
            "Telescope Simulator.TELESCOPE_TIMED_GUIDE_WE.TIMED_GUIDE_E",
            "100.0",
        ) in calls


def test_pulse_guide_negative_dec(mount):
    mount._connected = True
    with (
        patch("astrolabe.mount.indi.IndiClient.has_prop") as mock_has_prop,
        patch("astrolabe.mount.indi.IndiClient.setprop") as mock_setprop,
    ):

        def has_prop_mock(prop):
            if "TIMED_GUIDE" in prop:
                return True
            return False

        mock_has_prop.side_effect = has_prop_mock
        mount.pulse_guide(0, -50.0)

        calls = [(c.args[0], c.args[1]) for c in mock_setprop.call_args_list]
        assert (
            "Telescope Simulator.TELESCOPE_TIMED_GUIDE_NS.TIMED_GUIDE_S",
            "50.0",
        ) in calls


def test_set_tracking_auto_connects(mount):
    assert not mount.is_connected()
    with (
        patch("astrolabe.mount.indi.IndiClient.wait_for_device"),
        patch("astrolabe.mount.indi.IndiClient.setprop"),
        patch("astrolabe.mount.indi.IndiClient.has_prop", return_value=True),
    ):
        mount.set_tracking(True)
        assert mount.is_connected()


def test_slew_to_auto_connects(mount):
    assert not mount.is_connected()
    with (
        patch("astrolabe.mount.indi.IndiClient.wait_for_device"),
        patch("astrolabe.mount.indi.IndiClient.setprop"),
        patch("astrolabe.mount.indi.IndiClient.setprop_multi"),
        patch("astrolabe.mount.indi.IndiClient.has_prop", return_value=True),
        patch("astrolabe.mount.indi.icrs_to_jnow", return_value=(0.0, 0.0)),
    ):
        mount.slew_to(0.0, 0.0)
        assert mount.is_connected()


def test_get_state_auto_connects(mount):
    assert not mount.is_connected()
    with (
        patch("astrolabe.mount.indi.IndiClient.wait_for_device"),
        patch("astrolabe.mount.indi.IndiClient.setprop"),
        patch("astrolabe.mount.indi.IndiClient.has_prop", return_value=False),
        patch("astrolabe.mount.indi.IndiClient.getprop_value", return_value=""),
    ):
        state = mount.get_state()
        assert mount.is_connected()
        assert state.connected is True


@pytest.mark.integration
def test_indi_mount_slew_and_state(config):
    if shutil.which("indi_getprop") is None or shutil.which("indi_setprop") is None:
        pytest.skip("INDI tools not available")

    mount = IndiMountBackend(config)
    try:
        mount.connect()
    except Exception as exc:  # noqa: BLE001 - integration environment may be missing
        pytest.skip(f"INDI device not available: {exc}")

    client = mount._client

    # Best-effort: unpark and enable tracking (simulators may require this for motion).
    if client.has_prop("Telescope Simulator.TELESCOPE_PARK.UNPARK"):
        client.setprop(
            "Telescope Simulator.TELESCOPE_PARK.UNPARK", "On", kind="s", soft=True
        )
    if client.has_prop("Telescope Simulator.TELESCOPE_TRACK_STATE.TRACK_ON"):
        client.setprop(
            "Telescope Simulator.TELESCOPE_TRACK_STATE.TRACK_ON",
            "On",
            kind="s",
            soft=True,
        )
    time.sleep(0.5)

    state0 = mount.get_state()
    if state0.ra_rad is None or state0.dec_rad is None:
        pytest.skip("Mount state missing coordinates")

    try:
        target_ra0 = float(
            client.getprop_value("Telescope Simulator.TARGET_EOD_COORD.RA")
        )
        target_dec0 = float(
            client.getprop_value("Telescope Simulator.TARGET_EOD_COORD.DEC")
        )
    except Exception as exc:  # noqa: BLE001 - simulator properties may vary
        pytest.skip(f"TARGET_EOD_COORD not available: {exc}")

    target_ra = (state0.ra_rad + 0.5) % (2.0 * math.pi)
    target_dec = max(min(state0.dec_rad + 0.2, math.pi / 2 - 0.1), -math.pi / 2 + 0.1)
    d_ra0 = (state0.ra_rad - target_ra + math.pi) % (2.0 * math.pi) - math.pi
    d_dec0 = state0.dec_rad - target_dec
    initial_err = math.hypot(d_ra0 * math.cos(target_dec), d_dec0)

    mount.slew_to(target_ra, target_dec)

    final_state = None
    moved = False

    # Verify either target or current coordinate changes after the slew.
    change_deadline = time.monotonic() + 5.0
    while time.monotonic() < change_deadline:
        try:
            target_ra1 = float(
                client.getprop_value("Telescope Simulator.TARGET_EOD_COORD.RA")
            )
            target_dec1 = float(
                client.getprop_value("Telescope Simulator.TARGET_EOD_COORD.DEC")
            )
        except Exception:
            target_ra1 = target_ra0
            target_dec1 = target_dec0

        state_check = mount.get_state()
        if state_check.ra_rad is not None and state_check.dec_rad is not None:
            d_ra_curr = (state_check.ra_rad - state0.ra_rad + math.pi) % (
                2.0 * math.pi
            ) - math.pi
            d_dec_curr = state_check.dec_rad - state0.dec_rad
            if math.hypot(d_ra_curr * math.cos(state0.dec_rad), d_dec_curr) > 1e-4:
                moved = True

        if abs(target_ra1 - target_ra0) > 1e-6 or abs(target_dec1 - target_dec0) > 1e-6:
            moved = True

        if moved:
            break
        time.sleep(0.5)

    if not moved:
        pytest.skip(
            "No coordinate changes observed; simulator may be parked or tracking disabled."
        )

    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        final_state = mount.get_state()
        if final_state.ra_rad is None or final_state.dec_rad is None:
            time.sleep(0.5)
            continue

        d_ra_t = (final_state.ra_rad - target_ra + math.pi) % (2.0 * math.pi) - math.pi
        d_dec_t = final_state.dec_rad - target_dec
        angular_err = math.hypot(d_ra_t * math.cos(target_dec), d_dec_t)

        if angular_err < max(0.05, initial_err * 0.2):
            break

        time.sleep(0.5)

    assert final_state is not None
    assert final_state.ra_rad is not None
    assert final_state.dec_rad is not None

    d_ra = (final_state.ra_rad - target_ra + math.pi) % (2.0 * math.pi) - math.pi
    d_dec = final_state.dec_rad - target_dec
    angular_err = math.hypot(d_ra * math.cos(target_dec), d_dec)
    assert angular_err < initial_err * 0.5


@pytest.mark.integration
def test_indi_mount_connect_and_state(config):
    if shutil.which("indi_getprop") is None or shutil.which("indi_setprop") is None:
        pytest.skip("INDI tools not available")

    mount = IndiMountBackend(config)
    try:
        mount.connect()
    except Exception as exc:  # noqa: BLE001 - integration environment may be missing
        pytest.skip(f"INDI device not available: {exc}")

    state = mount.get_state()
    assert state.connected is True
    assert state.ra_rad is not None
    assert state.dec_rad is not None
