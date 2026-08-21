"""Unit pins for the shared output emitter."""

from __future__ import annotations

import datetime
import json
from types import SimpleNamespace

import pytest

from astrolabe.cli.output import emit


def _args():
    return SimpleNamespace(json=True)


def test_emit_does_not_stringify_unserializable_values_by_default(capsys):
    """`json_default` is opt-in: unexpected types must fail loudly, not stringify."""
    with pytest.raises(TypeError):
        emit(_args(), "demo", ok=True, data={"when": datetime.date(2026, 1, 2)})


def test_emit_stringifies_when_the_command_asks_for_it(capsys):
    emit(
        _args(),
        "demo",
        ok=True,
        data={"when": datetime.date(2026, 1, 2)},
        json_default=str,
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"] == {"when": "2026-01-02"}


def test_json_mode_suppresses_human_text(capsys):
    emit(_args(), "demo", ok=True, data=None, human="human only")
    captured = capsys.readouterr()
    assert json.loads(captured.out)["command"] == "demo"
    assert captured.err == ""
