"""Output primitives for the CLI: the JSON envelope, the ``--json`` fork, and
the human formatters shared by more than one handler.

The JSON envelope and the error object defined in `docs/cli.md` §3 are
constructed here and nowhere else.
"""

from __future__ import annotations

import datetime
import json
import sys
from collections.abc import Callable
from typing import Any, TextIO

from astrolabe.solver.types import SolveResult
from astrolabe.util.format import rad_to_dms, rad_to_deg, rad_to_hms


def json_envelope(
    command: str, ok: bool, data: Any = None, error: dict | None = None
) -> dict:
    return {
        "ok": ok,
        "command": command,
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "data": data,
        "error": error,
    }


def error_object(code: str, message: str, details: dict | None = None) -> dict:
    return {"code": code, "message": message, "details": details}


def emit(
    args,
    command: str,
    *,
    ok: bool,
    data: Any = None,
    error: dict | None = None,
    human: str | None = None,
    human_stream: TextIO | None = None,
    json_default: Callable[[Any], Any] | None = None,
) -> None:
    """Emit one result: a single JSON envelope, or the human text.

    ``json_default`` is the ``json.dumps`` fallback for values the encoder does
    not understand. It is deliberately opt-in: a command that grows an
    unserializable field should fail loudly rather than silently stringify it.
    """
    if getattr(args, "json", False):
        print(
            json.dumps(
                json_envelope(command, ok, data, error),
                indent=2,
                default=json_default,
            )
        )
        return
    if human is not None:
        print(human, file=human_stream or sys.stdout)


def emit_error(
    args,
    command: str,
    *,
    code: str,
    message: str,
    details: dict | None = None,
    data: Any = None,
    exit_code: int = 1,
    human: str | None = None,
) -> int:
    emit(
        args,
        command,
        ok=False,
        data=data,
        error=error_object(code, message, details),
        human=message if human is None else human,
        human_stream=sys.stderr,
    )
    return exit_code


def emit_result(
    args,
    command: str,
    result,
    *,
    failure_code: str,
    failure_message: str,
    ok: bool | None = None,
    data: Any = None,
    human: str | None = None,
    human_stream: TextIO | None = None,
) -> int:
    """Render a service result dataclass as a success/failure envelope."""
    succeeded = result.success if ok is None else ok
    error = (
        None
        if succeeded
        else error_object(failure_code, result.message or failure_message)
    )
    emit(
        args,
        command,
        ok=succeeded,
        data=result.__dict__ if data is None else data,
        error=error,
        human=human,
        human_stream=human_stream,
    )
    return 0 if succeeded else 1


def format_ra(ra_rad: float | None) -> str:
    return f"RA: {rad_to_hms(ra_rad)}" if ra_rad is not None else "RA: None"


def format_dec(dec_rad: float | None) -> str:
    return f"Dec: {rad_to_dms(dec_rad)}" if dec_rad is not None else "Dec: None"


def format_solve_summary(
    result: SolveResult, *, raw_output_on_failure: bool = False
) -> str:
    """Human summary of a plate-solve result.

    ``raw_output_on_failure`` appends the solver's raw output after a failed
    solve; only `astrolabe solve --verbose` asks for it.
    """
    lines = [
        f"Success: {result.success}",
        format_ra(result.ra_rad),
        format_dec(result.dec_rad),
        f"Pixel scale: {result.pixel_scale_arcsec}",
        f"Rotation: {rad_to_deg(result.rotation_rad):.3f}°"
        if result.rotation_rad is not None
        else "Rotation: None",
        f"RMS: {result.rms_arcsec}",
        f"Stars: {result.num_stars}",
        f"Message: {result.message}",
    ]
    if raw_output_on_failure and not result.success and result.raw_output:
        lines += ["", "--- ASTAP output ---", result.raw_output]
    return "\n".join(lines)
