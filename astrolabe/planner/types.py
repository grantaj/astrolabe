from dataclasses import dataclass, field
import datetime
from typing import Optional, Sequence


@dataclass
class ObserverLocation:
    latitude_deg: float
    longitude_deg: float
    elevation_m: float | None = None
    name: str | None = None
    bortle: int | None = None
    sqm: float | None = None


@dataclass
class PlannerConstraints:
    sun_altitude_max_deg: float
    min_altitude_deg: float
    min_duration_min: float
    moon_separation_min_deg: float
    moon_separation_strict_deg: float
    moon_illumination_strict_threshold: float


@dataclass(frozen=True)
class Target:
    id: str
    name: str
    ra_deg: float
    dec_deg: float
    type: str
    common_name: str | None = None
    messier_id: str | None = None
    caldwell_id: str | None = None
    mag: float | None = None
    size_arcmin: float | None = None
    surface_brightness: float | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class PlannerRequest:
    window_start_utc: datetime.datetime
    window_end_utc: datetime.datetime
    location: ObserverLocation
    constraints: PlannerConstraints
    mode: str = "visual"
    limit: int = 10


@dataclass
class PlannerEntry:
    id: str
    name: str
    target_type: str
    best_time_utc: datetime.datetime
    peak_altitude_deg: float
    time_above_min_alt_min: float
    moon_separation_deg: float
    moon_illumination: float
    difficulty: str
    score: float
    score_components: dict
    best_time_hint_utc: datetime.datetime | None = None
    common_name: str | None = None
    messier_id: str | None = None
    caldwell_id: str | None = None
    viewability: str | None = None
    notes: list[str] = field(default_factory=list)
    ra_deg: float | None = None
    dec_deg: float | None = None
    size_arcmin: float | None = None
    mag: float | None = None
    surface_brightness: float | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class PlannerSection:
    name: str
    entries: Sequence[PlannerEntry]


@dataclass
class PlannerResult:
    window_start_utc: datetime.datetime
    window_end_utc: datetime.datetime
    location: ObserverLocation
    sections: Sequence[PlannerSection]
    mode: str | None = None
    message: Optional[str] = None
