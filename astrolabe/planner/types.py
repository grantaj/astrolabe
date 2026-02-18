from dataclasses import dataclass
import datetime
from typing import Optional, Sequence


@dataclass
class ObserverLocation:
    latitude_deg: float
    longitude_deg: float
    elevation_m: float | None = None


@dataclass
class PlannerConstraints:
    sun_altitude_max_deg: float
    min_altitude_deg: float
    min_duration_min: float
    moon_separation_min_deg: float
    moon_separation_strict_deg: float
    moon_illumination_strict_threshold: float


@dataclass
class PlannerRequest:
    window_start_utc: datetime.datetime
    window_end_utc: datetime.datetime
    location: ObserverLocation
    constraints: PlannerConstraints


@dataclass
class PlannerEntry:
    name: str
    target_type: str
    best_time_utc: datetime.datetime
    peak_altitude_deg: float
    time_above_min_alt_min: float
    moon_separation_deg: float
    moon_illumination: float
    difficulty: str


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
    message: Optional[str] = None
