import json
import datetime
from dataclasses import asdict
from .types import PlannerResult


def format_json(result: PlannerResult) -> str:
    return json.dumps(asdict(result), indent=2, default=str)


def format_text(result: PlannerResult, verbose: bool = False) -> str:
    lines: list[str] = []
    local_tz = datetime.datetime.now().astimezone().tzinfo
    window_short = _window_is_short(result.window_start_utc, result.window_end_utc)
    start_local = _format_window_time(result.window_start_utc, local_tz, window_short)
    end_local = _format_window_time(result.window_end_utc, local_tz, window_short)
    lines.append("Astrolabe Planner")
    lines.append("=================")
    lines.append(f"Window (local): {start_local} → {end_local}")
    if result.location.name:
        lines.append(f"Site: {result.location.name}")
    lines.append(
        f"Location: lat {result.location.latitude_deg:.3f}°, lon {result.location.longitude_deg:.3f}°"
    )
    if result.location.bortle is not None or result.location.sqm is not None:
        parts = []
        if result.location.bortle is not None:
            parts.append(f"Bortle {result.location.bortle}")
        if result.location.sqm is not None:
            parts.append(f"SQM {result.location.sqm:.1f}")
        lines.append("Sky: " + ", ".join(parts))
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
        rows = []
        for idx, entry in enumerate(section.entries, start=1):
            best_local = _format_entry_time(entry.best_time_utc, local_tz, window_short)
            display_name = _display_name_verbose(entry) if verbose else _display_name(entry)
            view = entry.viewability or entry.difficulty
            note_parts = list(entry.notes) if entry.notes else []
            if entry.best_time_hint_utc:
                hint_time = _format_entry_time(entry.best_time_hint_utc, local_tz, window_short)
                note_parts.append(f"better around {hint_time}")
            notes = "; ".join(note_parts)
            rows.append(
                {
                    "idx": f"{idx:>2}.",
                    "name": display_name,
                    "type": entry.target_type,
                    "view": view,
                    "best": best_local,
                    "notes": notes,
                    "score": f"{entry.score:.1f}",
                    "alt": f"{entry.peak_altitude_deg:.0f}°",
                    "moon": f"{entry.moon_separation_deg:.0f}°",
                }
            )

        if not rows:
            continue

        name_w = min(40, max(len(r["name"]) for r in rows))
        type_w = min(18, max(len(r["type"]) for r in rows))
        view_w = min(7, max(len(r["view"]) for r in rows))
        best_w = min(5, max(len(r["best"]) for r in rows)) if window_short else min(16, max(len(r["best"]) for r in rows))
        for r in rows:
            name = _pad(_truncate(r["name"], name_w), name_w)
            ttype = _pad(_truncate(_display_type(r["type"]), type_w), type_w)
            view = _pad(_truncate(r["view"], view_w), view_w)
            best = _pad(_truncate(r["best"], best_w), best_w)
            notes = r["notes"]
            if verbose:
                line_prefix = (
                    f"{r['idx']} {name}  {ttype}  {view}  {best}  "
                    f"score {r['score']}  alt {r['alt']}  moon {r['moon']}"
                )
                line = f"{line_prefix}  {notes}" if notes else line_prefix
                lines.append(line)
            else:
                line_prefix = f"{r['idx']} {name}  {ttype}  {view}  {best}"
                line = f"{line_prefix}  {notes}" if notes else line_prefix
                lines.append(line)
    return "\n".join(lines)


def _to_local(dt: datetime.datetime, tz: datetime.tzinfo | None) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    if tz is None:
        tz = datetime.timezone.utc
    return dt.astimezone(tz).isoformat(timespec="minutes")


def _window_is_short(start: datetime.datetime, end: datetime.datetime) -> bool:
    return (end - start) < datetime.timedelta(days=1)


def _format_window_time(
    dt: datetime.datetime,
    tz: datetime.tzinfo | None,
    short: bool,
) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    if tz is None:
        tz = datetime.timezone.utc
    local = dt.astimezone(tz)
    if short:
        return local.strftime("%H:%M")
    return local.strftime("%Y-%m-%d %H:%M")


def _format_entry_time(
    dt: datetime.datetime,
    tz: datetime.tzinfo | None,
    short: bool,
) -> str:
    if short:
        return _format_window_time(dt, tz, short=True)
    return _format_window_time(dt, tz, short=False)


def _truncate(value: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    return value[: width - 3] + "..."


def _pad(value: str, width: int) -> str:
    if len(value) >= width:
        return value
    return value + (" " * (width - len(value)))




def _display_name(entry) -> str:
    if entry.common_name and entry.common_name.lower() != entry.name.lower():
        if entry.messier_id:
            return f"{entry.common_name} ({entry.messier_id})"
        if entry.caldwell_id:
            return f"{entry.common_name} ({entry.caldwell_id})"
        return f"{entry.common_name} ({entry.id})"
    if entry.messier_id:
        return f"{entry.messier_id} ({entry.id})"
    if entry.caldwell_id:
        return f"{entry.caldwell_id} ({entry.id})"
    return entry.name


def _display_name_verbose(entry) -> str:
    ids = []
    if entry.messier_id:
        ids.append(entry.messier_id)
    if entry.caldwell_id:
        ids.append(entry.caldwell_id)
    if entry.id:
        ids.append(entry.id)
    id_text = ", ".join(ids)
    if entry.common_name and entry.common_name.lower() != entry.name.lower():
        return f"{entry.common_name} ({id_text})"
    if entry.name:
        return f"{entry.name} ({id_text})" if id_text else entry.name
    return id_text


def _display_type(value: str) -> str:
    if not value:
        return ""
    return value.replace("_", " ").replace("+", "/")
