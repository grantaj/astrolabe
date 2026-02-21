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
from .providers import get_catalog_providers, list_solar_system_targets


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
        targets.extend(self._load_solar_system_targets(window_start, window_end))
        window_minutes = (window_end - window_start).total_seconds() / 60.0

        entries: list[PlannerEntry] = []
        rejection = _RejectionStats()
        showpiece_entries: list[PlannerEntry] = []
        solar_entries: list[PlannerEntry] = []
        mid_time = window_start + (window_end - window_start) / 2
        moon_ra, moon_dec = moon_ra_dec_rad(mid_time)
        moon_illum = moon_illumination_fraction(mid_time)
        moon_alt_deg = math.degrees(
            ra_dec_to_alt_az(
                moon_ra,
                moon_dec,
                math.radians(location.latitude_deg),
                location.longitude_deg,
                mid_time,
            )[0]
        )

        sun_alt_deg = _min_sun_alt_deg(
            window_start,
            window_end,
            location,
        )

        for target in targets:
            features = _compute_target_features(
                target,
                window_start,
                window_end,
                location,
                constraints.min_altitude_deg,
                constraints,
                mode=mode,
                aperture_mm=self._config.planner_aperture_mm,
            )
            if features["max_alt_deg"] < constraints.min_altitude_deg:
                rejection.below_min_alt += 1
                continue
            if features["time_above_min_alt_min"] < constraints.min_duration_min:
                rejection.too_short += 1
                continue
            feasible = apply_feasibility_constraints(
                Feasibility(
                    max_alt_deg=features["max_alt_deg"],
                    time_above_min_alt_min=features["time_above_min_alt_min"],
                    sun_alt_deg=sun_alt_deg,
                ),
                constraints,
            )
            if not feasible:
                rejection.sun_gate += 1
                continue

            best_time = features["best_time_utc"]
            time_metrics = _time_metrics(target, best_time, location)
            moon_sep_deg = time_metrics.moon_sep_deg
            sun_sep_deg = time_metrics.sun_sep_deg

            score, components = score_target(
                max_alt_deg=time_metrics.alt_deg,
                min_alt_deg=constraints.min_altitude_deg,
                time_above_min_min=features["time_above_min_alt_min"],
                window_duration_min=window_minutes,
                moon_sep_deg=moon_sep_deg,
                moon_illum=time_metrics.moon_illum,
                moon_alt_deg=time_metrics.moon_alt_deg,
                moon_up_fraction=1.0 if time_metrics.moon_alt_deg > 0 else 0.0,
                sun_alt_deg=time_metrics.sun_alt_deg,
                sun_sep_deg=sun_sep_deg,
                target_type=target.type,
                mag=target.mag,
                size_arcmin=target.size_arcmin,
                size_major_arcmin=target.size_major_arcmin,
                size_minor_arcmin=target.size_minor_arcmin,
                surface_brightness=target.surface_brightness,
                mode=mode,
                moon_sep_min_deg=constraints.moon_separation_min_deg,
                moon_sep_strict_deg=constraints.moon_separation_strict_deg,
                moon_illum_strict_threshold=constraints.moon_illumination_strict_threshold,
                bortle=location.bortle,
                sqm=location.sqm,
                aperture_mm=self._config.planner_aperture_mm,
            )

            notes = _build_notes(
                target=target,
                max_alt_deg=time_metrics.alt_deg,
                time_above_min_alt_min=features["time_above_min_alt_min"],
                window_duration_min=window_minutes,
                moon_sep_deg=moon_sep_deg,
                moon_illum=time_metrics.moon_illum,
                moon_alt_deg=time_metrics.moon_alt_deg,
                sun_alt_deg=time_metrics.sun_alt_deg,
                sun_sep_deg=sun_sep_deg,
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
                    caldwell_id=target.caldwell_id,
                    target_type=target.type,
                    best_time_utc=features["best_time_utc"],
                    best_time_hint_utc=features["best_time_hint_utc"],
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
                    size_major_arcmin=target.size_major_arcmin,
                    size_minor_arcmin=target.size_minor_arcmin,
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
                message=_build_no_target_message(rejection, constraints, sun_alt_deg, window_start, window_end, location),
            )

        # Note: The `limit` value applies only to the main ranked `entries`
        # list. Showpiece and solar entries are gathered from `all_entries`
        # (the full ranked list) and may add targets back into the final
        # `sections` output. This is intentional (Option A): the `limit`
        # constrains the primary ranked list while allowing curated
        # supplemental sections (showpieces/solar) to include additional
        # entries.
        entries.sort(key=lambda e: e.score, reverse=True)
        all_entries = list(entries)
        if limit is not None:
            entries = entries[:limit]

        for entry in all_entries:
            if _is_showpiece_entry(entry) and _is_showpiece_worthy(entry, constraints):
                showpiece_entries.append(entry)
            if _is_solar_entry(entry) and _is_solar_worthy(entry, constraints):
                solar_entries.append(entry)

        sections = _build_sections(entries, showpiece_entries, solar_entries)

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
            bortle=config.mount_site_bortle,
            sqm=config.mount_site_sqm,
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

    def _load_solar_system_targets(
        self,
        window_start: datetime.datetime,
        window_end: datetime.datetime,
    ) -> list[Target]:
        return list_solar_system_targets(window_start, window_end)


def _compute_target_features(
    target: Target,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    location: ObserverLocation,
    min_alt_deg: float,
    constraints: PlannerConstraints,
    include_hint: bool = True,
    mode: str = "visual",
    aperture_mm: float | None = None,
) -> dict:
    context = _window_context(
        target,
        window_start,
        window_end,
        location,
        min_alt_deg,
    )
    window_minutes = (window_end - window_start).total_seconds() / 60.0
    best_time = _best_time_by_score(
        target,
        context.samples,
        context.altitudes,
        location,
        constraints,
        context.time_above_min,
        window_minutes=window_minutes,
        mode=mode,
        aperture_mm=aperture_mm,
    )
    best_time_hint = None
    if include_hint:
        best_time_hint = _best_time_hint(
            target,
            window_start,
            window_end,
            location,
            constraints,
            mode=mode,
            aperture_mm=aperture_mm,
        )
    return {
        "max_alt_deg": context.max_alt,
        "best_time_utc": best_time,
        "best_time_hint_utc": best_time_hint,
        "time_above_min_alt_min": context.time_above_min,
        "moon_up_fraction": context.moon_up_fraction,
        "sun_alt_min_deg": context.sun_alt_min_deg,
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


class _WindowContext:
    def __init__(
        self,
        *,
        samples: list[datetime.datetime],
        altitudes: list[float],
        max_alt: float,
        time_above_min: float,
        moon_up_fraction: float,
        sun_alt_min_deg: float,
    ) -> None:
        self.samples = samples
        self.altitudes = altitudes
        self.max_alt = max_alt
        self.time_above_min = time_above_min
        self.moon_up_fraction = moon_up_fraction
        self.sun_alt_min_deg = sun_alt_min_deg


class _TimeMetrics:
    def __init__(
        self,
        *,
        alt_deg: float,
        sun_alt_deg: float,
        sun_sep_deg: float,
        moon_alt_deg: float,
        moon_sep_deg: float,
        moon_illum: float,
    ) -> None:
        self.alt_deg = alt_deg
        self.sun_alt_deg = sun_alt_deg
        self.sun_sep_deg = sun_sep_deg
        self.moon_alt_deg = moon_alt_deg
        self.moon_sep_deg = moon_sep_deg
        self.moon_illum = moon_illum


def _time_metrics(
    target: Target,
    t: datetime.datetime,
    location: ObserverLocation,
) -> _TimeMetrics:
    lat_rad = math.radians(location.latitude_deg)
    alt_rad, _ = ra_dec_to_alt_az(
        math.radians(target.ra_deg),
        math.radians(target.dec_deg),
        lat_rad,
        location.longitude_deg,
        t,
    )
    alt_deg = math.degrees(alt_rad)
    sun_ra, sun_dec = sun_ra_dec_rad(t)
    sun_alt_rad, _ = ra_dec_to_alt_az(sun_ra, sun_dec, lat_rad, location.longitude_deg, t)
    sun_alt_deg = math.degrees(sun_alt_rad)
    sun_sep_deg = math.degrees(
        angular_separation_rad(
            math.radians(target.ra_deg),
            math.radians(target.dec_deg),
            sun_ra,
            sun_dec,
        )
    )
    moon_ra, moon_dec = moon_ra_dec_rad(t)
    moon_alt_rad, _ = ra_dec_to_alt_az(moon_ra, moon_dec, lat_rad, location.longitude_deg, t)
    moon_alt_deg = math.degrees(moon_alt_rad)
    moon_sep_deg = math.degrees(
        angular_separation_rad(
            math.radians(target.ra_deg),
            math.radians(target.dec_deg),
            moon_ra,
            moon_dec,
        )
    )
    moon_illum = moon_illumination_fraction(t)
    return _TimeMetrics(
        alt_deg=alt_deg,
        sun_alt_deg=sun_alt_deg,
        sun_sep_deg=sun_sep_deg,
        moon_alt_deg=moon_alt_deg,
        moon_sep_deg=moon_sep_deg,
        moon_illum=moon_illum,
    )


def _window_context(
    target: Target,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    location: ObserverLocation,
    min_alt_deg: float,
) -> _WindowContext:
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
    time_above_min = _time_above_threshold(samples, altitudes, min_alt_deg)
    max_alt = max(altitudes) if altitudes else -90.0
    moon_up_fraction = _moon_up_fraction(window_start, window_end, location)
    sun_alt_min = _min_sun_alt_deg(window_start, window_end, location)
    return _WindowContext(
        samples=samples,
        altitudes=altitudes,
        max_alt=max_alt,
        time_above_min=time_above_min,
        moon_up_fraction=moon_up_fraction,
        sun_alt_min_deg=sun_alt_min,
    )


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


def _min_sun_alt_deg(
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    location: ObserverLocation,
) -> float:
    lat_rad = math.radians(location.latitude_deg)
    times = _sample_times(window_start, window_end, cadence_min=10)
    min_alt = 90.0
    for t in times:
        sun_ra, sun_dec = sun_ra_dec_rad(t)
        alt_rad, _ = ra_dec_to_alt_az(sun_ra, sun_dec, lat_rad, location.longitude_deg, t)
        alt_deg = math.degrees(alt_rad)
        if alt_deg < min_alt:
            min_alt = alt_deg
    return min_alt


def _best_time_by_score(
    target: Target,
    times: list[datetime.datetime],
    altitudes: list[float],
    location: ObserverLocation,
    constraints: PlannerConstraints,
    time_above_min: float,
    window_minutes: float,
    mode: str,
    aperture_mm: float | None,
) -> datetime.datetime:
    lat_rad = math.radians(location.latitude_deg)
    best_time = times[0]
    best_score = -1.0
    for t, alt_deg in zip(times, altitudes):
        sun_ra, sun_dec = sun_ra_dec_rad(t)
        sun_alt_rad, _ = ra_dec_to_alt_az(sun_ra, sun_dec, lat_rad, location.longitude_deg, t)
        sun_alt_deg = math.degrees(sun_alt_rad)
        sun_sep_deg = math.degrees(
            angular_separation_rad(
                math.radians(target.ra_deg),
                math.radians(target.dec_deg),
                sun_ra,
                sun_dec,
            )
        )
        moon_ra, moon_dec = moon_ra_dec_rad(t)
        moon_alt_rad, _ = ra_dec_to_alt_az(moon_ra, moon_dec, lat_rad, location.longitude_deg, t)
        moon_alt_deg = math.degrees(moon_alt_rad)
        moon_sep_deg = math.degrees(
            angular_separation_rad(
                math.radians(target.ra_deg),
                math.radians(target.dec_deg),
                moon_ra,
                moon_dec,
            )
        )
        moon_illum = moon_illumination_fraction(t)
        moon_up_fraction = 1.0 if moon_alt_deg > 0 else 0.0
        score, _ = score_target(
            max_alt_deg=alt_deg,
            min_alt_deg=constraints.min_altitude_deg,
            time_above_min_min=time_above_min,
            window_duration_min=window_minutes,
            moon_sep_deg=moon_sep_deg,
            moon_illum=moon_illum,
            moon_alt_deg=moon_alt_deg,
            moon_up_fraction=moon_up_fraction,
            sun_alt_deg=sun_alt_deg,
            sun_sep_deg=sun_sep_deg,
            target_type=target.type,
            mag=target.mag,
            size_arcmin=target.size_arcmin,
            size_major_arcmin=target.size_major_arcmin,
            size_minor_arcmin=target.size_minor_arcmin,
            surface_brightness=target.surface_brightness,
            mode=mode,
            moon_sep_min_deg=constraints.moon_separation_min_deg,
            moon_sep_strict_deg=constraints.moon_separation_strict_deg,
            moon_illum_strict_threshold=constraints.moon_illumination_strict_threshold,
            bortle=location.bortle,
            sqm=location.sqm,
            aperture_mm=aperture_mm,
        )
        if score > best_score:
            best_score = score
            best_time = t
    return best_time


def _moon_up_fraction(
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    location: ObserverLocation,
) -> float:
    lat_rad = math.radians(location.latitude_deg)
    times = _sample_times(window_start, window_end, cadence_min=10)
    if not times:
        return 0.0
    up = 0
    for t in times:
        ra_moon, dec_moon = moon_ra_dec_rad(t)
        alt_rad, _ = ra_dec_to_alt_az(ra_moon, dec_moon, lat_rad, location.longitude_deg, t)
        if alt_rad > 0:
            up += 1
    return up / max(1, len(times))


def _best_time_hint(
    target: Target,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    location: ObserverLocation,
    constraints: PlannerConstraints,
    mode: str,
    aperture_mm: float | None,
) -> datetime.datetime | None:
    # Re-run the same windowed feature evaluation on an extended window,
    # and suggest the best time only if it lies just outside the requested window.
    extended_start = window_start - datetime.timedelta(hours=1)
    extended_end = window_end + datetime.timedelta(hours=1)

    features_ext = _compute_target_features(
        target,
        extended_start,
        extended_end,
        location,
        constraints.min_altitude_deg,
        constraints,
        include_hint=False,
        mode=mode,
        aperture_mm=aperture_mm,
    )
    sun_alt_ext = features_ext["sun_alt_min_deg"]
    feasible = apply_feasibility_constraints(
        Feasibility(
            max_alt_deg=features_ext["max_alt_deg"],
            time_above_min_alt_min=features_ext["time_above_min_alt_min"],
            sun_alt_deg=sun_alt_ext,
        ),
        constraints,
    )
    if not feasible:
        return None

    best_time = features_ext["best_time_utc"]
    if window_start <= best_time <= window_end:
        return None
    if best_time < window_start and (window_start - best_time) <= datetime.timedelta(hours=1):
        return best_time
    if best_time > window_end and (best_time - window_end) <= datetime.timedelta(hours=1):
        return best_time
    return None


class _RejectionStats:
    def __init__(self) -> None:
        self.below_min_alt = 0
        self.too_short = 0
        self.sun_gate = 0


def _build_no_target_message(
    rejection: _RejectionStats,
    constraints: PlannerConstraints,
    sun_alt_min_deg: float,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    location: ObserverLocation,
) -> str:
    parts = ["No viable targets in this window."]
    if rejection.sun_gate > 0:
        parts.append(
            f"Sun never below {constraints.sun_altitude_max_deg:.0f}° (min {sun_alt_min_deg:.1f}°)."
        )
        suggestion = _suggest_dark_start(window_start, window_end, location, constraints.sun_altitude_max_deg)
        if suggestion:
            parts.append(f"Try starting around {suggestion}.")
    if rejection.below_min_alt > 0:
        parts.append(
            f"{rejection.below_min_alt} targets never reached {constraints.min_altitude_deg:.0f}°."
        )
    if rejection.too_short > 0:
        parts.append(
            f"{rejection.too_short} targets above {constraints.min_altitude_deg:.0f}° "
            f"for less than {constraints.min_duration_min:.0f} min."
        )
    return " ".join(parts)


def _suggest_dark_start(
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    location: ObserverLocation,
    sun_altitude_max_deg: float,
) -> str | None:
    local_tz = datetime.datetime.now().astimezone().tzinfo
    lat_rad = math.radians(location.latitude_deg)
    samples = _sample_times(window_start, window_end, cadence_min=5)
    for t in samples:
        sun_ra, sun_dec = sun_ra_dec_rad(t)
        alt_rad, _ = ra_dec_to_alt_az(sun_ra, sun_dec, lat_rad, location.longitude_deg, t)
        if math.degrees(alt_rad) <= sun_altitude_max_deg:
            return t.astimezone(local_tz).isoformat(timespec="minutes")
    # look ahead up to 6 hours for next dark window
    extended_end = window_end + datetime.timedelta(hours=6)
    samples = _sample_times(window_end, extended_end, cadence_min=5)
    for t in samples:
        sun_ra, sun_dec = sun_ra_dec_rad(t)
        alt_rad, _ = ra_dec_to_alt_az(sun_ra, sun_dec, lat_rad, location.longitude_deg, t)
        if math.degrees(alt_rad) <= sun_altitude_max_deg:
            return t.astimezone(local_tz).isoformat(timespec="minutes")
    return None


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
    sun_alt_deg: float,
    sun_sep_deg: float,
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

    if sun_alt_deg > -18.0 and sun_sep_deg < 90.0:
        notes.append("Twilight glow")

    return notes[:2]


def _build_sections(
    entries: list[PlannerEntry],
    showpieces: list[PlannerEntry],
    solar_entries: list[PlannerEntry],
) -> list[PlannerSection]:
    sections: dict[str, list[PlannerEntry]] = {}
    for entry in entries:
        name = _section_for_entry(entry)
        sections.setdefault(name, []).append(entry)

    if showpieces:
        sections["Showpieces"] = _merge_unique(showpieces, sections.get("Showpieces", []))

    sections["Showpieces"] = _limit_showpieces(sections.get("Showpieces", []))

    if solar_entries:
        sections["Solar System"] = _merge_unique(solar_entries, sections.get("Solar System", []))
        sections["Solar System"] = _limit_solar(sections.get("Solar System", []))

    ordered = []
    for name in ("Showpieces", "Solar System", "Recommended", "Clusters", "Deep Sky", "Other"):
        if name in sections:
            ordered.append(PlannerSection(name=name, entries=sections[name]))
    for name, items in sections.items():
        if name not in {s.name for s in ordered}:
            ordered.append(PlannerSection(name=name, entries=items))
    return ordered


def _section_for_entry(entry: PlannerEntry) -> str:
    tags = {t.lower() for t in entry.tags}
    if "solar_system" in tags:
        return "Solar System"
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
    if "solar_system" in tags:
        return False
    return "showpiece" in tags or "southern_showpiece" in tags


def _is_showpiece_worthy(entry: PlannerEntry, constraints: PlannerConstraints) -> bool:
    if entry.peak_altitude_deg < constraints.min_altitude_deg + 5:
        return False
    if entry.time_above_min_alt_min < constraints.min_duration_min:
        return False
    return entry.score >= 60.0


def _is_solar_entry(entry: PlannerEntry) -> bool:
    tags = {t.lower() for t in entry.tags}
    return "solar_system" in tags


def _is_solar_worthy(entry: PlannerEntry, constraints: PlannerConstraints) -> bool:
    if entry.peak_altitude_deg < constraints.min_altitude_deg:
        return False
    if entry.time_above_min_alt_min < constraints.min_duration_min:
        return False
    return entry.score >= 40.0


def _limit_showpieces(entries: list[PlannerEntry]) -> list[PlannerEntry]:
    filtered = [e for e in entries if e.viewability in (None, "easy", "medium")]
    return sorted(filtered, key=lambda e: e.score, reverse=True)[:10]


def _limit_solar(entries: list[PlannerEntry]) -> list[PlannerEntry]:
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
