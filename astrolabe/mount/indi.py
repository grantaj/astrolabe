from __future__ import annotations

import datetime
import logging
import math
import time

from astrolabe.indi.client import IndiClient
from astrolabe.errors import BackendError
from .base import MountBackend, MountState

logger = logging.getLogger(__name__)

try:
    from astropy.coordinates import SkyCoord, FK5
    from astropy.time import Time
    import astropy.units as u

    ASTROPY_AVAILABLE = True
except ImportError:
    ASTROPY_AVAILABLE = False

# Coordinate conversion constants
_RAD_TO_HOURS = 12.0 / math.pi
_RAD_TO_DEGREES = 180.0 / math.pi
_HOURS_TO_RAD = math.pi / 12.0
_DEGREES_TO_RAD = math.pi / 180.0

# Mount I/O wait times
_CONNECT_WAIT_S = 0.2
_COORD_SET_WAIT_S = 0.1

# INDI property state values
_INDI_ON = "On"
_INDI_OFF = "Off"
_INDI_BUSY = "Busy"


def _rad_to_hours(rad: float) -> float:
    return rad * _RAD_TO_HOURS


def _rad_to_degrees(rad: float) -> float:
    return rad * _RAD_TO_DEGREES


def _hours_to_rad(hours: float) -> float:
    return hours * _HOURS_TO_RAD


def _degrees_to_rad(degrees: float) -> float:
    return degrees * _DEGREES_TO_RAD


def icrs_to_jnow(
    ra_rad: float, dec_rad: float, time_utc: datetime.datetime
) -> tuple[float, float]:
    if not ASTROPY_AVAILABLE:
        raise RuntimeError(
            "astropy is required for coordinate frame conversion. "
            "Install with: pip install astropy"
        )
    c = SkyCoord(ra=ra_rad * u.rad, dec=dec_rad * u.rad, frame="icrs")
    jnow = c.transform_to(FK5(equinox=Time(time_utc)))
    return jnow.ra.rad, jnow.dec.rad


def jnow_to_icrs(
    ra_rad: float, dec_rad: float, time_utc: datetime.datetime
) -> tuple[float, float]:
    if not ASTROPY_AVAILABLE:
        raise RuntimeError(
            "astropy is required for coordinate frame conversion. "
            "Install with: pip install astropy"
        )
    c = SkyCoord(
        ra=ra_rad * u.rad, dec=dec_rad * u.rad, frame=FK5(equinox=Time(time_utc))
    )
    icrs = c.transform_to("icrs")
    return icrs.ra.rad, icrs.dec.rad


class IndiMountBackend(MountBackend):
    """INDI mount backend.

    Coordinates are expressed as ICRS in radians for the public interface.
    """
    def __init__(self, config):
        self._config = config
        self.host = config.indi_host
        self.port = config.indi_port
        self.device = config.mount_device
        self._client = IndiClient(self.host, self.port)
        self._connected = False

    def connect(self) -> None:
        self._client.wait_for_device(self.device)
        self._client.setprop(f"{self.device}.CONNECTION.CONNECT", "On", soft=False)
        time.sleep(_CONNECT_WAIT_S)
        self._connected = True

    def disconnect(self) -> None:
        if not self._connected:
            return
        self._client.setprop(f"{self.device}.CONNECTION.DISCONNECT", "On", soft=True)
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def get_state(self) -> MountState:
        if not self._connected:
            self.connect()

        # Determine coordinate property
        has_jnow = self._client.has_prop(f"{self.device}.EQUATORIAL_EOD_COORD.RA")
        has_j2000 = self._client.has_prop(f"{self.device}.EQUATORIAL_COORD.RA")

        ra_rad = None
        dec_rad = None
        now_utc = datetime.datetime.now(datetime.timezone.utc)

        if has_jnow:
            ra_str = self._client.getprop_value(
                f"{self.device}.EQUATORIAL_EOD_COORD.RA"
            )
            dec_str = self._client.getprop_value(
                f"{self.device}.EQUATORIAL_EOD_COORD.DEC"
            )
            ra_jnow = _hours_to_rad(float(ra_str))
            dec_jnow = _degrees_to_rad(float(dec_str))
            ra_rad, dec_rad = jnow_to_icrs(ra_jnow, dec_jnow, now_utc)
        elif has_j2000:
            ra_str = self._client.getprop_value(f"{self.device}.EQUATORIAL_COORD.RA")
            dec_str = self._client.getprop_value(f"{self.device}.EQUATORIAL_COORD.DEC")
            ra_rad = _hours_to_rad(float(ra_str))
            dec_rad = _degrees_to_rad(float(dec_str))

        # Tracking state
        tracking = False
        if self._client.has_prop(f"{self.device}.TELESCOPE_TRACK_STATE.TRACK_ON"):
            track_on = self._client.getprop_value(
                f"{self.device}.TELESCOPE_TRACK_STATE.TRACK_ON"
            )
            tracking = track_on.lower() == _INDI_ON.lower()

        # Slewing state: observe EQUATORIAL_EOD_COORD (or EQUATORIAL_COORD) property state.
        # The property state will be "Busy" during a slew operation.
        slewing = False
        if has_jnow:
            coord_prop = f"{self.device}.EQUATORIAL_EOD_COORD"
        elif has_j2000:
            coord_prop = f"{self.device}.EQUATORIAL_COORD"
        else:
            coord_prop = None

        if coord_prop is not None:
            try:
                prop_state = self._client.getprop_state(f"{coord_prop}.RA")
                slewing = prop_state.lower() == _INDI_BUSY.lower()
            except Exception:
                logger.debug(
                    "Failed to read slew state for %s", coord_prop, exc_info=True
                )

        return MountState(
            connected=True,
            ra_rad=ra_rad,
            dec_rad=dec_rad,
            tracking=tracking,
            slewing=slewing,
            timestamp_utc=now_utc,
        )

    def slew_to(self, ra_rad: float, dec_rad: float) -> None:
        if not self._connected:
            self.connect()

        ra_rad = ra_rad % (2.0 * math.pi)
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        has_jnow = self._client.has_prop(f"{self.device}.EQUATORIAL_EOD_COORD.RA")
        has_j2000 = self._client.has_prop(f"{self.device}.EQUATORIAL_COORD.RA")

        # Set ON_COORD_SET to SLEW (optional feature, soft failure allowed)
        if self._client.has_prop(f"{self.device}.ON_COORD_SET.SLEW"):
            self._client.setprop(
                f"{self.device}.ON_COORD_SET.TRACK", _INDI_OFF, soft=True
            )
            self._client.setprop(
                f"{self.device}.ON_COORD_SET.SYNC", _INDI_OFF, soft=True
            )
            self._client.setprop(
                f"{self.device}.ON_COORD_SET.SLEW", _INDI_ON, soft=True
            )
            time.sleep(_COORD_SET_WAIT_S)

        if has_jnow:
            ra_jnow, dec_jnow = icrs_to_jnow(ra_rad, dec_rad, now_utc)
            ra_jnow = ra_jnow % (2.0 * math.pi)
            self._client.setprop(
                f"{self.device}.EQUATORIAL_EOD_COORD.RA",
                str(_rad_to_hours(ra_jnow)),
                soft=False,
            )
            self._client.setprop(
                f"{self.device}.EQUATORIAL_EOD_COORD.DEC",
                str(_rad_to_degrees(dec_jnow)),
                soft=False,
            )
        elif has_j2000:
            self._client.setprop(
                f"{self.device}.EQUATORIAL_COORD.RA",
                str(_rad_to_hours(ra_rad)),
                soft=False,
            )
            self._client.setprop(
                f"{self.device}.EQUATORIAL_COORD.DEC",
                str(_rad_to_degrees(dec_rad)),
                soft=False,
            )
        else:
            raise BackendError(
                f"Mount device '{self.device}' has no supported coordinate property "
                "(EQUATORIAL_EOD_COORD or EQUATORIAL_COORD)."
            )

    def sync(self, ra_rad: float, dec_rad: float) -> None:
        if not self._connected:
            self.connect()

        ra_rad = ra_rad % (2.0 * math.pi)
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        has_jnow = self._client.has_prop(f"{self.device}.EQUATORIAL_EOD_COORD.RA")
        has_j2000 = self._client.has_prop(f"{self.device}.EQUATORIAL_COORD.RA")

        if self._client.has_prop(f"{self.device}.ON_COORD_SET.SYNC"):
            self._client.setprop(
                f"{self.device}.ON_COORD_SET.TRACK", _INDI_OFF, soft=True
            )
            self._client.setprop(
                f"{self.device}.ON_COORD_SET.SLEW", _INDI_OFF, soft=True
            )
            self._client.setprop(
                f"{self.device}.ON_COORD_SET.SYNC", _INDI_ON, soft=True
            )
            time.sleep(_COORD_SET_WAIT_S)

        if has_jnow:
            ra_jnow, dec_jnow = icrs_to_jnow(ra_rad, dec_rad, now_utc)
            ra_jnow = ra_jnow % (2.0 * math.pi)
            self._client.setprop(
                f"{self.device}.EQUATORIAL_EOD_COORD.RA",
                str(_rad_to_hours(ra_jnow)),
                soft=False,
            )
            self._client.setprop(
                f"{self.device}.EQUATORIAL_EOD_COORD.DEC",
                str(_rad_to_degrees(dec_jnow)),
                soft=False,
            )
        elif has_j2000:
            self._client.setprop(
                f"{self.device}.EQUATORIAL_COORD.RA",
                str(_rad_to_hours(ra_rad)),
                soft=False,
            )
            self._client.setprop(
                f"{self.device}.EQUATORIAL_COORD.DEC",
                str(_rad_to_degrees(dec_rad)),
                soft=False,
            )
        else:
            raise BackendError(
                f"Mount device '{self.device}' has no supported coordinate property "
                "(EQUATORIAL_EOD_COORD or EQUATORIAL_COORD)."
            )

    def stop(self) -> None:
        if not self._connected:
            return
        if self._client.has_prop(f"{self.device}.TELESCOPE_ABORT_MOTION.ABORT"):
            self._client.setprop(
                f"{self.device}.TELESCOPE_ABORT_MOTION.ABORT", _INDI_ON, soft=True
            )

    def park(self) -> None:
        if not self._connected:
            self.connect()
        if self._client.has_prop(f"{self.device}.TELESCOPE_PARK.PARK"):
            self._client.setprop(
                f"{self.device}.TELESCOPE_PARK.PARK", _INDI_ON, soft=True
            )

    def set_tracking(self, enabled: bool) -> None:
        if not self._connected:
            self.connect()
        # TELESCOPE_TRACK_STATE is a 1OFMANY switch: set the desired element to "On"
        if enabled:
            prop = f"{self.device}.TELESCOPE_TRACK_STATE.TRACK_ON"
        else:
            prop = f"{self.device}.TELESCOPE_TRACK_STATE.TRACK_OFF"
        if self._client.has_prop(prop):
            self._client.setprop(prop, _INDI_ON, soft=True)

    def pulse_guide(self, ra_ms: float, dec_ms: float) -> None:
        """Send a timed pulse guide command to the mount.

        Args:
            ra_ms: RA pulse duration in milliseconds. Positive = east, negative = west.
            dec_ms: DEC pulse duration in milliseconds. Positive = north, negative = south.
        """
        if not self._connected:
            self.connect()

        if ra_ms != 0 and self._client.has_prop(
            f"{self.device}.TELESCOPE_TIMED_GUIDE_WE.TIMED_GUIDE_E"
        ):
            if ra_ms > 0:
                self._client.setprop(
                    f"{self.device}.TELESCOPE_TIMED_GUIDE_WE.TIMED_GUIDE_E",
                    str(ra_ms),
                    soft=True,
                )
            else:
                if self._client.has_prop(
                    f"{self.device}.TELESCOPE_TIMED_GUIDE_WE.TIMED_GUIDE_W"
                ):
                    self._client.setprop(
                        f"{self.device}.TELESCOPE_TIMED_GUIDE_WE.TIMED_GUIDE_W",
                        str(-ra_ms),
                        soft=True,
                    )

        if dec_ms != 0 and self._client.has_prop(
            f"{self.device}.TELESCOPE_TIMED_GUIDE_NS.TIMED_GUIDE_N"
        ):
            if dec_ms > 0:
                self._client.setprop(
                    f"{self.device}.TELESCOPE_TIMED_GUIDE_NS.TIMED_GUIDE_N",
                    str(dec_ms),
                    soft=True,
                )
            else:
                if self._client.has_prop(
                    f"{self.device}.TELESCOPE_TIMED_GUIDE_NS.TIMED_GUIDE_S"
                ):
                    self._client.setprop(
                        f"{self.device}.TELESCOPE_TIMED_GUIDE_NS.TIMED_GUIDE_S",
                        str(-dec_ms),
                        soft=True,
                    )
        else:
            logger.warning(
                "Mount device '%s' has no supported coordinate property "
                "(EQUATORIAL_EOD_COORD or EQUATORIAL_COORD).",
                self.device,
            )
