"""Handler plumbing shared by every CLI command: the prologue (logging,
config, dry-run notice), backend wiring, and the single exception-to-exit-code
mapping described in `docs/cli.md` §2.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from astrolabe.camera import get_camera_backend
from astrolabe.cli.output import emit_error
from astrolabe.config import Config, load_config
from astrolabe.errors import (
    AstrolabeError,
    BackendError,
    NotImplementedFeature,
    ServiceError,
)
from astrolabe.mount import get_mount_backend
from astrolabe.solver import get_solver_backend

_LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "error": logging.ERROR,
}

# (exception type, error code, exit code). Order is significant: the most
# specific type wins.
_ERROR_MAPPING: tuple[tuple[type[AstrolabeError], str, int], ...] = (
    (NotImplementedFeature, "not_implemented", 2),
    (BackendError, "backend_error", 2),
    (ServiceError, "service_error", 1),
    (AstrolabeError, "internal_error", 2),
)


def init_logging(level: str | None) -> None:
    if not level:
        return
    logging.basicConfig(level=_LOG_LEVELS.get(level, logging.INFO))


def config_path(args) -> Path | None:
    if args is None:
        return None
    path = getattr(args, "config", None)
    return Path(path) if path else None


def note_dry_run(args, subject: str) -> None:
    if getattr(args, "dry_run", False):
        print(f"--dry-run has no effect for {subject}.", file=sys.stderr)


def prepare(args, dry_run_subject: str | None = None) -> Config:
    """Handler prologue: logging, config, and the dry-run notice."""
    init_logging(getattr(args, "log_level", None))
    config = load_config(config_path(args))
    if dry_run_subject is not None:
        note_dry_run(args, dry_run_subject)
    return config


def mount_camera_solver(config):
    return (
        get_mount_backend(config),
        get_camera_backend(config),
        get_solver_backend(config),
    )


def handle_error(args, command: str, exc: AstrolabeError) -> int:
    """Map an Astrolabe exception to an error envelope and an exit code.

    Every handler routes AstrolabeError here, except `update`, which keeps its
    pre-existing broad ``except Exception`` -> "update_failed", exit 1.
    """
    code, exit_code = next(
        (c, x) for exc_type, c, x in _ERROR_MAPPING if isinstance(exc, exc_type)
    )
    message = str(exc)
    return emit_error(
        args,
        command,
        code=code,
        message=message,
        exit_code=exit_code,
        human=message
        if isinstance(exc, NotImplementedFeature)
        else f"Error: {message}",
    )
