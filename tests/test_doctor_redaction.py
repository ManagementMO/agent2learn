"""The support report must be safe to paste into a public GitHub issue.

This is the highest-stakes test in the diagnostics path. A student pastes `a2l doctor
--report` into a bug report expecting the tool to have protected them; anything that leaks
is out of their hands the moment they press submit. So the assertions here are deliberately
paranoid: they check the rendered body for the *values*, not for the code paths that were
supposed to remove them.

The report is built from an allowlist rather than a denylist. A denylist only removes the
leaks someone anticipated, and every future check would silently become a new way to leak.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent2learn import config as config_module
from agent2learn import doctor
from agent2learn.session import Session, SessionCookie
from agent2learn.vault import Vault

# Values a real student's machine would carry, chosen so a leak is unmistakable in output.
STUDENT_NAME = "Alex Example"
STUDENT_ID = "99999999"
COURSE_CODE = "MSE245_sec01_1261"
ORG_UNIT = "1148573"
COOKIE_VALUE = "s3cr3t-session-value-that-must-never-appear"  # pragma: allowlist secret


@pytest.fixture
def loaded_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[config_module.Config, Vault]:
    """A vault and config carrying every category the report is required to redact."""
    home = tmp_path / "home"
    vault_root = home / "agent2learn"
    course = vault_root / "Fall 2026" / COURSE_CODE / "_meta"
    course.mkdir(parents=True)
    (course / "content_map.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "topics": [
                    {
                        "source_key": f"uwaterloo:{ORG_UNIT}:topic:1",
                        "source_id": "1",
                        "title": f"{STUDENT_NAME} graded feedback",
                        "kind": "File",
                        "availability": "markdown_ready",
                        "course_code": COURSE_CODE,
                        "course_name": "Materials Science",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (vault_root / ".a2l").mkdir(parents=True, exist_ok=True)
    (vault_root / ".a2l" / "VERSION").write_text("1", encoding="utf-8")

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    cfg = config_module.Config(vault=vault_root, school="uwaterloo")
    return cfg, Vault(vault_root)


def _session() -> Session:
    return Session(
        base_url="https://learn.uwaterloo.ca",
        cookies=(
            SessionCookie(
                name="d2lSessionVal",
                value=COOKIE_VALUE,
                domain="learn.uwaterloo.ca",
                path="/d2l",
                secure=True,
            ),
        ),
        xsrf="xsrf-token-value",
        harvested_at=datetime(2026, 8, 25, 9, 0, tzinfo=UTC),
        user_id=STUDENT_ID,
    )


def test_report_leaks_nothing(
    loaded_environment: tuple[config_module.Config, Vault], monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, vault = loaded_environment
    monkeypatch.setattr(doctor.session_module, "load", _session)

    body = doctor.report(doctor.run_checks(cfg, vault))

    for secret in (
        STUDENT_NAME,
        "Alex",
        STUDENT_ID,
        COURSE_CODE,
        "MSE245",
        ORG_UNIT,
        COOKIE_VALUE,
        "d2lSessionVal",
        "xsrf-token-value",
        str(Path.home()),
        str(cfg.vault),
    ):
        assert secret not in body, f"{secret!r} leaked into the support report"

    # The home directory is replaced, not deleted: a reader still needs to see the shape.
    assert "~" in body


def test_report_is_built_from_an_allowlist_not_a_denylist(
    loaded_environment: tuple[config_module.Config, Vault], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A check invented later must not be able to leak by default.

    A denylist only removes what someone thought of. This injects a check whose every field
    is hostile and asserts none of it reaches the body — which can only hold if unknown
    content is dropped rather than scrubbed.
    """
    cfg, vault = loaded_environment
    monkeypatch.setattr(doctor.session_module, "load", lambda: None)

    checks = doctor.run_checks(cfg, vault)
    checks.append(
        doctor.Check(
            group="Invented Later",
            name="leaky.check",
            status="fail",
            detail=f"{STUDENT_NAME} {STUDENT_ID} {COOKIE_VALUE} {Path.home()}",
            fix=f"remove {COURSE_CODE} from {Path.home()}",
        )
    )

    body = doctor.report(checks)

    assert "unknown-check" in body
    for secret in (STUDENT_NAME, STUDENT_ID, COOKIE_VALUE, COURSE_CODE, str(Path.home())):
        assert secret not in body


def test_report_does_not_trust_an_opted_in_public_note(
    loaded_environment: tuple[config_module.Config, Vault], monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, vault = loaded_environment
    monkeypatch.setattr(doctor.session_module, "load", lambda: None)
    hostile = (
        "https://learn.example/d2l?token="
        + COOKIE_VALUE
        + " Authorization: Bearer "
        + COOKIE_VALUE
        + f" {STUDENT_NAME} {STUDENT_ID} {COURSE_CODE} {ORG_UNIT} 87% "
        + str(Path.home() / "private" / "file.md")
    )

    hostile_name = f"{COURSE_CODE}.{STUDENT_ID}.{COOKIE_VALUE}"
    body = doctor.report([doctor.Check("Later", hostile_name, "warn", "safe", public=hostile)])

    assert "unknown-check" in body
    for secret in (
        COOKIE_VALUE,
        STUDENT_NAME,
        STUDENT_ID,
        COURSE_CODE,
        ORG_UNIT,
        "87%",
        str(Path.home()),
        "Authorization",
        "Bearer",
        "token=",
        hostile_name,
    ):
        assert secret not in body


def test_report_never_contains_grades_or_cookie_material(
    loaded_environment: tuple[config_module.Config, Vault], monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, vault = loaded_environment
    monkeypatch.setattr(doctor.session_module, "load", _session)
    (vault.root / "Fall 2026" / COURSE_CODE / "_meta" / "my_grades.json").write_text(
        json.dumps([{"GradeObjectName": "Midterm", "DisplayedGrade": "87%"}]), encoding="utf-8"
    )

    body = doctor.report(doctor.run_checks(cfg, vault))

    for forbidden in ("87%", "Midterm", "DisplayedGrade", "Cookie", "Authorization", "Bearer"):
        assert forbidden not in body


def test_absolute_paths_are_replaced_with_a_tilde_everywhere(
    loaded_environment: tuple[config_module.Config, Vault], monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, vault = loaded_environment
    monkeypatch.setattr(doctor.session_module, "load", lambda: None)

    body = doctor.report(doctor.run_checks(cfg, vault))

    assert str(Path.home()) not in body
    # No absolute POSIX or Windows path survives anywhere in the body.
    for line in body.splitlines():
        assert not line.lstrip().startswith("/"), line
        assert ":\\" not in line, line


def test_render_is_human_readable_and_may_show_local_paths(
    loaded_environment: tuple[config_module.Config, Vault], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`render` is for the user's own terminal, so it is allowed what `report` is not.

    Keeping the two apart is the point: a redacted terminal view would be useless for
    debugging, and an unredacted issue body would be unsafe.
    """
    cfg, vault = loaded_environment
    monkeypatch.setattr(doctor.session_module, "load", lambda: None)

    text = doctor.render(doctor.run_checks(cfg, vault))

    assert "Environment" in text and "Filesystem" in text
    assert COOKIE_VALUE not in text, "cookie material is forbidden in every code path"
