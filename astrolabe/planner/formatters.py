import json
import datetime
from dataclasses import asdict
from .types import PlannerResult


def format_json(result: PlannerResult) -> str:
    return json.dumps(asdict(result), indent=2, default=str)


def format_text(result: PlannerResult) -> str:
    lines: list[str] = []
    local_tz = datetime.datetime.now().astimezone().tzinfo
    start_local = _to_local(result.window_start_utc, local_tz)
    end_local = _to_local(result.window_end_utc, local_tz)
    lines.append("Astrolabe Planner")
    lines.append("=================")
    lines.append(f"Window: {start_local} → {end_local}")
    if result.location.name:
        lines.append(f"Site: {result.location.name}")
    lines.append(
        f"Location: lat {result.location.latitude_deg:.3f}°, lon {result.location.longitude_deg:.3f}°"
    )
    if result.mode:
        lines.append(f"Mode: {result.mode}")
    if result.message:
        lines.append("")
        lines.append(result.message)
        return "\n".join(lines)

    for section in result.sections:
        lines.append("")
        lines.append(f"{section.name}")
        lines.append("-" * len(section.name))
        for idx, entry in enumerate(section.entries, start=1):
            best_local = _to_local(entry.best_time_utc, local_tz)
            display_name = _display_name(entry)
            notes = f" [{'; '.join(entry.notes)}]" if entry.notes else ""
            lines.append(
                f"{idx:>2}. {display_name} ({entry.target_type}) "
                f"score {entry.score:.1f} | "
                f"view {entry.viewability or entry.difficulty} | "
                f"best {best_local} | "
                f"max alt {entry.peak_altitude_deg:.0f}° | "
                f"moon {entry.moon_separation_deg:.0f}°{notes}"
            )
    return "\n".join(lines)


def _to_local(dt: datetime.datetime, tz: datetime.tzinfo | None) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    if tz is None:
        tz = datetime.timezone.utc
    return dt.astimezone(tz).isoformat(timespec="minutes")


def _display_name(entry) -> str:
    if entry.common_name and entry.common_name.lower() != entry.name.lower():
        if entry.messier_id:
            return f"{entry.common_name} ({entry.messier_id})"
        return f"{entry.common_name} ({entry.id})"
    if entry.messier_id:
        return f"{entry.messier_id} ({entry.id})"
    return entry.name
