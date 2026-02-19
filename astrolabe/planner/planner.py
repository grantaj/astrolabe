import datetime
from astrolabe.errors import NotImplementedFeature
from .types import (
    ObserverLocation,
    PlannerConstraints,
    PlannerRequest,
    PlannerResult,
)
from .providers import get_catalog_providers


DEFAULT_WINDOW_HOURS = 3
DEFAULT_SUN_ALT_MAX_DEG = -12.0
DEFAULT_MIN_ALT_DEG = 30.0
DEFAULT_MIN_DURATION_MIN = 30.0
DEFAULT_MOON_SEP_DEG = 35.0
DEFAULT_MOON_SEP_STRICT_DEG = 45.0
DEFAULT_MOON_ILLUM_STRICT = 0.5


class Planner:
    def __init__(self, config):
        self._config = config
        self._providers = get_catalog_providers()

    def plan(
        self,
        window_start_utc: datetime.datetime | None = None,
        window_end_utc: datetime.datetime | None = None,
        location: ObserverLocation | None = None,
        constraints: PlannerConstraints | None = None,
    ) -> PlannerResult:
        raise NotImplementedFeature("Planner not implemented")

    @staticmethod
    def default_request(config) -> PlannerRequest:
        now = datetime.datetime.now(datetime.timezone.utc)
        window_start = now
        window_end = now + datetime.timedelta(hours=DEFAULT_WINDOW_HOURS)

        location = ObserverLocation(
            latitude_deg=config.mount_site_latitude_deg,
            longitude_deg=config.mount_site_longitude_deg,
            elevation_m=config.mount_site_elevation_m,
        )

        constraints = PlannerConstraints(
            sun_altitude_max_deg=DEFAULT_SUN_ALT_MAX_DEG,
            min_altitude_deg=DEFAULT_MIN_ALT_DEG,
            min_duration_min=DEFAULT_MIN_DURATION_MIN,
            moon_separation_min_deg=DEFAULT_MOON_SEP_DEG,
            moon_separation_strict_deg=DEFAULT_MOON_SEP_STRICT_DEG,
            moon_illumination_strict_threshold=DEFAULT_MOON_ILLUM_STRICT,
        )

        return PlannerRequest(
            window_start_utc=window_start,
            window_end_utc=window_end,
            location=location,
            constraints=constraints,
        )
