"""Doctor must always end with exactly one next action, and grade honestly."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent2learn import config as config_module
from agent2learn import doctor
from agent2learn.session import Session, SessionCookie
from agent2learn.vault import Vault


def _vault(tmp_path: Path) -> Vault:
    root = tmp_path / "vault"
    (root / ".a2l").mkdir(parents=True, exist_ok=True)
    (root / ".a2l" / "VERSION").write_text("1", encoding="utf-8")
    return Vault(root)


def _cfg(vault: Vault) -> config_module.Config:
    return config_module.Config(vault=vault.root)


def _content_map(course: Path, rows: list[dict[str, object]]) -> None:
    (course / "_meta").mkdir(parents=True, exist_ok=True)
    (course / "_meta" / "content_map.json").write_text(
        json.dumps({"schema_version": 1, "topics": rows}), encoding="utf-8"
    )


def _row(index: int, availability: str) -> dict[str, object]:
    return {
        "source_key": f"uwaterloo:1:topic:{index}",
        "source_id": str(index),
        "title": f"Topic {index}",
        "kind": "File",
        "availability": availability,
        "course_code": "COURSE101",
        "course_name": "Intro",
    }


def _session(*, hours_old: float) -> Session:
    return Session(
        base_url="https://learn.uwaterloo.ca",
        cookies=(
            SessionCookie(
                name="d2lSessionVal",
                value="synthetic",  # pragma: allowlist secret
                domain="learn.uwaterloo.ca",
                path="/d2l",
                secure=True,
            ),
        ),
        xsrf=None,
        harvested_at=datetime.now(UTC) - timedelta(hours=hours_old),
        user_id="1",
    )


def test_exit_codes_are_zero_one_two() -> None:
    ok = [doctor.Check("Environment", "a", "ok", "fine")]
    warn = [*ok, doctor.Check("Session", "b", "warn", "stale", "run: a2l auth")]
    fail = [*warn, doctor.Check("Filesystem", "c", "fail", "broken", "fix it")]

    assert doctor.exit_code(ok) == 0
    assert doctor.exit_code(warn) == 1
    assert doctor.exit_code(fail) == 2


def test_render_suggests_exactly_one_command_and_prefers_failures() -> None:
    """Six suggestions is the same as none: the user closes the window."""
    checks = [
        doctor.Check("Session", "b", "warn", "stale", "run: a2l auth"),
        doctor.Check("Vault", "c", "warn", "empty", "run: a2l sync"),
        doctor.Check("Filesystem", "d", "fail", "unwritable", "check folder permissions"),
    ]

    text = doctor.render(checks)

    assert doctor.next_command(checks) == "check folder permissions"
    assert text.count("Next:") == 1
    assert "run: a2l sync" not in text


def test_render_offers_no_next_command_when_everything_passes() -> None:
    checks = [doctor.Check("Environment", "a", "ok", "fine")]

    text = doctor.render(checks)

    assert doctor.next_command(checks) is None
    assert "Next:" not in text
    assert "all clear" in text


def test_render_groups_in_a_stable_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _vault(tmp_path)
    monkeypatch.setattr(doctor.session_module, "load", lambda: None)

    text = doctor.render(doctor.run_checks(_cfg(vault), vault))
    order = [line for line in text.splitlines() if line and not line.startswith((" ", "N"))]

    assert order[:6] == [
        "Environment",
        "Filesystem",
        "Session",
        "Optional tools",
        "Skills",
        "Vault",
    ]


def test_session_backend_is_named_in_plain_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """'file' means nothing to a student; 'not encrypted' does."""
    vault = _vault(tmp_path)
    monkeypatch.setattr(doctor.session_module, "backend_name", lambda: "file")
    monkeypatch.setattr(doctor.session_module, "load", lambda: None)

    checks = doctor.run_checks(_cfg(vault), vault)
    backend = next(check for check in checks if check.name == "session.backend")

    assert backend.detail == "permission-restricted local file (not encrypted)"


def test_stale_session_warns_and_fresh_one_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)

    monkeypatch.setattr(doctor.session_module, "load", lambda: _session(hours_old=48))
    stale = doctor.run_checks(_cfg(vault), vault)
    assert next(c for c in stale if c.name == "session.age").status == "warn"

    monkeypatch.setattr(doctor.session_module, "load", lambda: _session(hours_old=1))
    fresh = doctor.run_checks(_cfg(vault), vault)
    assert next(c for c in fresh if c.name == "session.age").status == "ok"


def test_no_check_ever_reports_a_cookie_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)
    monkeypatch.setattr(doctor.session_module, "load", lambda: _session(hours_old=1))

    checks = doctor.run_checks(_cfg(vault), vault)
    everything = " ".join(f"{c.detail} {c.fix or ''} {c.public or ''}" for c in checks)

    for forbidden in ("synthetic", "d2lSessionVal", "Cookie"):
        assert forbidden not in everything


def test_windows_long_paths_is_informational_and_never_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """a2l handles long paths itself, so this must never be graded as the user's problem."""
    vault = _vault(tmp_path)
    monkeypatch.setattr(doctor.session_module, "load", lambda: None)

    check = next(c for c in doctor.run_checks(_cfg(vault), vault) if c.name == "fs.long_paths")

    assert check.status == "ok"
    assert check.fix is None


def test_long_absolute_paths_warn_about_other_tools_not_the_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)
    deep = vault.root / ("d" * 60) / ("e" * 60) / ("f" * 60) / ("g" * 60)
    deep.mkdir(parents=True)
    (deep / "file.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(doctor.session_module, "load", lambda: None)

    check = next(c for c in doctor.run_checks(_cfg(vault), vault) if c.name == "fs.longest_path")

    assert check.status == "warn"
    assert check.fix is not None
    assert "shorter vault root" in check.fix
    assert "registry" not in check.fix.casefold()


def test_vault_coverage_counts_citable_topics_and_gaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)
    _content_map(
        vault.root / "Fall 2026" / "COURSE101",
        [_row(1, "markdown_ready"), _row(2, "source_only"), _row(3, "unsupported_format")],
    )
    monkeypatch.setattr(doctor.session_module, "load", lambda: None)

    checks = doctor.run_checks(_cfg(vault), vault)

    assert next(c for c in checks if c.name == "vault.citable").detail == "1 of 3 topic(s) citable"
    assert next(c for c in checks if c.name == "vault.gaps").detail == "1 conversion gap(s)"


def test_tracked_private_files_fail_while_tracked_course_files_only_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ignore rules are not a privacy guarantee, and the two cases differ in severity."""
    vault = _vault(tmp_path)
    monkeypatch.setattr(doctor.session_module, "load", lambda: None)
    monkeypatch.setattr(doctor, "_inside_git_worktree", lambda root: True)

    monkeypatch.setattr(doctor, "_tracked_files", lambda root: ["Fall 2026/C/_meta/my_grades.json"])
    private = next(c for c in doctor.run_checks(_cfg(vault), vault) if c.name == "fs.git")
    assert private.status == "fail"

    monkeypatch.setattr(doctor, "_tracked_files", lambda root: ["Fall 2026/C/content/Lecture.pdf"])
    sources = next(c for c in doctor.run_checks(_cfg(vault), vault) if c.name == "fs.git")
    assert sources.status == "warn"

    monkeypatch.setattr(doctor, "_tracked_files", lambda root: ["README.md"])
    clean = next(c for c in doctor.run_checks(_cfg(vault), vault) if c.name == "fs.git")
    assert clean.status == "ok"


def test_open_notice_names_the_destination_before_anything_leaves_the_device() -> None:
    checks = [doctor.Check("Environment", "env.version", "ok", "agent2learn 0.1.0")]

    notice = doctor.open_notice(checks)

    assert doctor.ISSUE_URL in notice
    assert "leaves your device only when you press submit" in notice
    # The exact body is shown first, so consent is informed rather than implied.
    assert doctor.report(checks).strip() in notice


def test_issue_url_is_encoded_and_bounded() -> None:
    checks = [doctor.Check("Vault", f"check.{index}", "warn", "x") for index in range(4000)]

    url = doctor.issue_url(checks)

    assert url.startswith(doctor.ISSUE_URL)
    assert " " not in url and "\n" not in url
    assert len(url) < 40_000


def test_run_checks_never_raises_on_a_missing_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    """A diagnostic that crashes on a broken machine is worse than useless."""
    monkeypatch.setattr(doctor.session_module, "load", lambda: None)

    checks = doctor.run_checks(config_module.Config(vault=Path("/nonexistent/a2l")), None)

    assert doctor.exit_code(checks) in {1, 2}
    assert doctor.next_command(checks) is not None
