import json
from types import SimpleNamespace

import pytest

from astrolabe.cli.commands import run_resolve


def _args(
    target: str,
    *,
    json_output: bool = False,
    limit: int = 5,
    min_score: float | None = None,
):
    return SimpleNamespace(
        target=[target],
        limit=limit,
        min_score=min_score,
        json=json_output,
        log_level=None,
        config=None,
        dry_run=False,
    )


@pytest.fixture(autouse=True)
def _isolate_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))


def test_resolve_plain_output(capsys):
    exit_code = run_resolve(_args("IC0010"))
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "IC0010" in captured.out


def test_resolve_json_output(capsys):
    exit_code = run_resolve(_args("M110", json_output=True))
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["command"] == "resolve"
    assert payload["data"]["matches"]


def test_resolve_not_found(capsys):
    exit_code = run_resolve(_args("definitely-not-a-target"))
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Target not found" in captured.err
