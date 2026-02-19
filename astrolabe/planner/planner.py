import datetime
import math
from .astro import (
    angular_separation_rad,
    moon_illumination_fraction,
    moon_ra_dec_rad,
    ra_dec_to_alt_az,
    sun_ra_dec_rad,
)
from .filters import Feasibility, apply_feasibility_constraints
from .scoring import score_target
from .types import (
    ObserverLocation,
    PlannerConstraints,
    PlannerRequest,
    PlannerResult,
    PlannerSection,
    PlannerEntry,
    Target,
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
        mode: str | None = None,
        limit: int | None = None,
    ) -> PlannerResult:
        request = self.default_request(self._config)
        window_start = window_start_utc or request.window_start_utc
        window_end = window_end_utc or request.window_end_utc
        if window_start.tzinfo is None:
            window_start = window_start.replace(tzinfo=datetime.timezone.utc)
        if window_end.tzinfo is None:
            window_end = window_end.replace(tzinfo=datetime.timezone.utc)
        if window_end <= window_start:
            raise ValueError("Window end must be after window start")

        location = location or request.location
        if location.latitude_deg is None or location.longitude_deg is None:
            raise ValueError("Observer location is required (lat/lon)")

        constraints = constraints or request.constraints
        mode = (mode or request.mode or "visual").lower()
        limit = request.limit if limit is None else limit
        if limit is not None and limit <= 0:
            raise ValueError("Limit must be positive")
        if mode not in ("visual", "photo"):
            raise ValueError("Mode must be one of: visual, photo")

        targets = self._load_targets()
        window_minutes = (window_end - window_start).total_seconds() / 60.0

        entries: list[PlannerEntry] = []
        showpiece_entries: list[PlannerEntry] = []
        mid_time = window_start + (window_end - window_start) / 2
        sun_ra, sun_dec = sun_ra_dec_rad(mid_time)
        moon_ra, moon_dec = moon_ra_dec_rad(mid_time)
        moon_illum = moon_illumination_fraction(mid_time)

        sun_alt_deg = math.degrees(
            ra_dec_to_alt_az(
                sun_ra,
                sun_dec,
                math.radians(location.latitude_deg),
                location.longitude_deg,
                mid_time,
            )[0]
        )
        moon_alt_deg = math.degrees(
            ra_dec_to_alt_az(
                moon_ra,
                moon_dec,
                math.radians(location.latitude_deg),
                location.longitude_deg,
                mid_time,
            )[0]
        )

        for target in targets:
            features = _compute_target_features(
                target,
                window_start,
                window_end,
                location,
                constraints.min_altitude_deg,
            )
            feasible = apply_feasibility_constraints(
                Feasibility(
                    max_alt_deg=features["max_alt_deg"],
                    time_above_min_alt_min=features["time_above_min_alt_min"],
                    sun_alt_deg=sun_alt_deg,
                ),
                constraints,
            )
            if not feasible:
                continue

            moon_sep_deg = math.degrees(
                angular_separation_rad(
                    math.radians(target.ra_deg),
                    math.radians(target.dec_deg),
                    moon_ra,
                    moon_dec,
                )
            )

            score, components = score_target(
                max_alt_deg=features["max_alt_deg"],
                min_alt_deg=constraints.min_altitude_deg,
                time_above_min_min=features["time_above_min_alt_min"],
                window_duration_min=window_minutes,
                moon_sep_deg=moon_sep_deg,
                moon_illum=moon_illum,
                moon_alt_deg=moon_alt_deg,
                target_type=target.type,
                mag=target.mag,
                size_arcmin=target.size_arcmin,
                mode=mode,
                moon_sep_min_deg=constraints.moon_separation_min_deg,
                moon_sep_strict_deg=constraints.moon_separation_strict_deg,
                moon_illum_strict_threshold=constraints.moon_illumination_strict_threshold,
            )

            notes = _build_notes(
                target=target,
                max_alt_deg=features["max_alt_deg"],
                time_above_min_alt_min=features["time_above_min_alt_min"],
                window_duration_min=window_minutes,
                moon_sep_deg=moon_sep_deg,
                moon_illum=moon_illum,
                moon_alt_deg=moon_alt_deg,
                mode=mode,
                min_alt_deg=constraints.min_altitude_deg,
            )

            difficulty = _difficulty_from_score(score)
            viewability = _viewability_from_score(score)
            entries.append(
                PlannerEntry(
                    id=target.id,
                    name=target.name,
                    common_name=target.common_name,
                    messier_id=target.messier_id,
                    target_type=target.type,
                    best_time_utc=features["best_time_utc"],
                    peak_altitude_deg=features["max_alt_deg"],
                    time_above_min_alt_min=features["time_above_min_alt_min"],
                    moon_separation_deg=moon_sep_deg,
                    moon_illumination=moon_illum,
                    difficulty=difficulty,
                    score=score,
                    score_components=components,
                    viewability=viewability,
                    notes=notes,
                    ra_deg=target.ra_deg,
                    dec_deg=target.dec_deg,
                    size_arcmin=target.size_arcmin,
                    mag=target.mag,
                    surface_brightness=target.surface_brightness,
                    tags=target.tags,
                )
            )

        if not entries:
            return PlannerResult(
                window_start_utc=window_start,
                window_end_utc=window_end,
                location=location,
                sections=[],
                mode=mode,
                message="No viable targets in this window.",
            )

        entries.sort(key=lambda e: e.score, reverse=True)
        all_entries = list(entries)
        if limit is not None:
            entries = entries[:limit]

        for entry in all_entries:
            if _is_showpiece_entry(entry) and _is_showpiece_worthy(entry, constraints):
                showpiece_entries.append(entry)

        sections = _build_sections(entries, showpiece_entries, constraints)

        return PlannerResult(
            window_start_utc=window_start,
            window_end_utc=window_end,
            location=location,
            sections=sections,
            mode=mode,
            message=None,
        )

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
            mode="visual",
            limit=10,
        )

    def _load_targets(self) -> list[Target]:
        targets: list[Target] = []
        for provider in self._providers:
            targets.extend(provider.list_targets())
        return targets


def _compute_target_features(
    target: Target,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    location: ObserverLocation,
    min_alt_deg: float,
) -> dict:
    lat_rad = math.radians(location.latitude_deg)
    samples = _sample_times(window_start, window_end, cadence_min=10)
    altitudes: list[float] = []
    for t in samples:
        alt_rad, _ = ra_dec_to_alt_az(
            math.radians(target.ra_deg),
            math.radians(target.dec_deg),
            lat_rad,
            location.longitude_deg,
            t,
        )
        altitudes.append(math.degrees(alt_rad))
    max_alt = max(altitudes)
    best_time = samples[altitudes.index(max_alt)]
    time_above_min = _time_above_threshold(samples, altitudes, min_alt_deg)
    return {
        "max_alt_deg": max_alt,
        "best_time_utc": best_time,
        "time_above_min_alt_min": time_above_min,
    }


def _sample_times(
    start: datetime.datetime,
    end: datetime.datetime,
    cadence_min: int,
) -> list[datetime.datetime]:
    total_min = (end - start).total_seconds() / 60.0
    if total_min <= cadence_min:
        return [start, end]
    steps = max(1, math.ceil(total_min / cadence_min))
    delta = (end - start) / steps
    return [start + delta * i for i in range(steps + 1)]


def _time_above_threshold(
    times: list[datetime.datetime],
    altitudes: list[float],
    threshold: float,
) -> float:
    if len(times) < 2:
        return 0.0
    total = 0.0
    for i in range(len(times) - 1):
        alt_mid = (altitudes[i] + altitudes[i + 1]) / 2.0
        if alt_mid >= threshold:
            total += (times[i + 1] - times[i]).total_seconds() / 60.0
    return total


def _difficulty_from_score(score: float) -> str:
    if score >= 80.0:
        return "easy"
    if score >= 60.0:
        return "medium"
    return "hard"


def _build_notes(
    *,
    target: Target,
    max_alt_deg: float,
    time_above_min_alt_min: float,
    window_duration_min: float,
    moon_sep_deg: float,
    moon_illum: float,
    moon_alt_deg: float,
    mode: str,
    min_alt_deg: float,
) -> list[str]:
    notes: list[str] = []
    if max_alt_deg >= 60:
        notes.append("High and well-placed")
    elif max_alt_deg < min_alt_deg + 5:
        notes.append("Low altitude")

    if window_duration_min > 0:
        if time_above_min_alt_min / window_duration_min >= 0.6:
            notes.append("Long observing window")
        elif time_above_min_alt_min / window_duration_min <= 0.2:
            notes.append("Short observing window")

    if moon_alt_deg >= 0:
        if moon_sep_deg >= 80:
            notes.append("Far from Moon")
        elif moon_sep_deg <= 35:
            notes.append("Close to Moon")

    if moon_illum >= 0.7:
        if "cluster" in target.type.lower():
            notes.append("Good in bright Moon (cluster)")
        else:
            notes.append("Bright Moon")

    if target.size_arcmin is not None:
        pref_min, pref_max = (5.0, 60.0) if mode == "photo" else (10.0, 120.0)
        if target.size_arcmin > pref_max * 1.5:
            notes.append("Large target; may not fit in FOV")
        elif target.size_arcmin < pref_min * 0.5:
            notes.append("Small target; benefits from steady seeing")

    return notes[:2]


def _build_sections(
    entries: list[PlannerEntry],
    showpieces: list[PlannerEntry],
    constraints: PlannerConstraints,
) -> list[PlannerSection]:
    sections: dict[str, list[PlannerEntry]] = {}
    for entry in entries:
        name = _section_for_entry(entry)
        sections.setdefault(name, []).append(entry)

    if showpieces:
        sections["Showpieces"] = _merge_unique(showpieces, sections.get("Showpieces", []))

    sections["Showpieces"] = _limit_showpieces(sections.get("Showpieces", []))

    ordered = []
    for name in ("Showpieces", "Recommended", "Clusters", "Deep Sky", "Other"):
        if name in sections:
            ordered.append(PlannerSection(name=name, entries=sections[name]))
    for name, items in sections.items():
        if name not in {s.name for s in ordered}:
            ordered.append(PlannerSection(name=name, entries=items))
    return ordered


def _section_for_entry(entry: PlannerEntry) -> str:
    tags = {t.lower() for t in entry.tags}
    if "showpiece" in tags or "southern_showpiece" in tags:
        return "Showpieces"
    t = entry.target_type.lower()
    if "cluster" in t:
        return "Clusters"
    if "nebula" in t or "galaxy" in t:
        return "Deep Sky"
    return "Recommended"


def _is_showpiece_entry(entry: PlannerEntry) -> bool:
    tags = {t.lower() for t in entry.tags}
    return "showpiece" in tags or "southern_showpiece" in tags


def _is_showpiece_worthy(entry: PlannerEntry, constraints: PlannerConstraints) -> bool:
    if entry.peak_altitude_deg < constraints.min_altitude_deg + 5:
        return False
    if entry.time_above_min_alt_min < constraints.min_duration_min:
        return False
    return entry.score >= 60.0


def _limit_showpieces(entries: list[PlannerEntry]) -> list[PlannerEntry]:
    entries = sorted(entries, key=lambda e: e.score, reverse=True)
    return entries[:5]


def _merge_unique(primary: list[PlannerEntry], secondary: list[PlannerEntry]) -> list[PlannerEntry]:
    seen = set()
    combined: list[PlannerEntry] = []
    for entry in primary + secondary:
        if entry.id in seen:
            continue
        seen.add(entry.id)
        combined.append(entry)
    return combined


def _viewability_from_score(score: float) -> str:
    if score >= 75.0:
        return "easy"
    if score >= 55.0:
        return "medium"
    return "hard"
