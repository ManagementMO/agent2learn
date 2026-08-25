"""Tests for the metadata-only calibrated course listing command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agent2learn import config
from agent2learn.cli import app


def _write_calibration(state: Path) -> None:
    state.mkdir(parents=True, exist_ok=True)
    (state / "calibration.json").write_text(
        json.dumps(
            {
                "calibrated_at": "2026-08-25T12:00:00Z",
                "courses": [
                    {
                        "code": "COURSE202_sec02_1261",
                        "end_date": None,
                        "is_active": False,
                        "name": "Past Example",
                        "org_unit_id": 222222,
                        "start_date": "2026-01-05T14:00:00.000Z",
                        "term": "1261",
                    },
                    {
                        "code": "COURSE101_sec01_1265",
                        "end_date": None,
                        "is_active": True,
                        "name": "Current Example",
                        "org_unit_id": 111111,
                        "start_date": "2026-05-05T14:00:00.000Z",
                        "term": "1265",
                    },
                ],
                "download_template": None,
                "le": "1.96",
                "lp": "1.62",
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )


def test_courses_requires_calibration_and_prints_one_safe_next_command(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "state_dir", lambda: tmp_path)

    result = CliRunner().invoke(app, ["courses"])

    assert result.exit_code == 3
    assert result.stdout == ""
    assert "run: a2l auth" in result.stderr
    assert "Traceback" not in result.output


def test_courses_default_is_active_academic_and_json_is_deterministic(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "state_dir", lambda: tmp_path)
    _write_calibration(tmp_path)

    result = CliRunner().invoke(app, ["courses", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "all_terms": False,
        "courses": [
            {
                "code": "COURSE101_sec01_1265",
                "is_active": True,
                "name": "Current Example",
                "org_unit_id": 111111,
                "term": "1265",
            }
        ],
        "distinct_terms": ["1265"],
    }


def test_courses_all_terms_includes_inactive_offerings_and_summary(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "state_dir", lambda: tmp_path)
    _write_calibration(tmp_path)

    result = CliRunner().invoke(app, ["courses", "--all-terms"])

    assert result.exit_code == 0
    assert "Distinct terms: 2" in result.stdout
    assert "Winter 2026 (1261)" in result.stdout
    assert "Spring 2026 (1265)" in result.stdout
    assert "COURSE202_sec02_1261 [222222]" in result.stdout
