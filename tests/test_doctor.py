"""Doctor must always end with exactly one next action, and grade honestly."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO, Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest

from agent2learn import config as config_module
from agent2learn import doctor
from agent2learn.errors import SessionExpired
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


class _DoctorClient:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get_json(self, path: str) -> object:
        self.calls.append(path)
        response = self.responses[path]
        if isinstance(response, BaseException):
            raise response
        return response


def test_exit_codes_are_zero_one_two() -> None:
    ok = [doctor.Check("Environment", "a", "ok", "fine")]
    warn = [*ok, doctor.Check("Session", "b", "warn", "stale", "run: a2l auth")]
    fail = [*warn, doctor.Check("Filesystem", "c", "fail", "broken", "fix it")]

    assert doctor.exit_code(ok) == 0
    assert doctor.exit_code(warn) == 1
    assert doctor.exit_code(fail) == 2


def test_render_suggests_exactly_one_registered_command() -> None:
    """Manual repair prose stays in detail; the single command slot remains executable."""
    checks = [
        doctor.Check("Session", "b", "warn", "stale", "run: a2l auth"),
        doctor.Check("Vault", "c", "warn", "empty", "run: a2l sync"),
        doctor.Check("Filesystem", "d", "fail", "unwritable", "check folder permissions"),
    ]

    text = doctor.render(checks)

    assert doctor.next_command(checks) == "run: a2l auth"
    assert text.count("Next:") == 1
    assert "Next: a2l auth" in text
    assert "run: a2l sync" not in text


def test_render_uses_the_safe_default_next_command_when_everything_passes() -> None:
    checks = [doctor.Check("Environment", "a", "ok", "fine")]

    text = doctor.render(checks)

    assert doctor.next_command(checks) == "run: a2l sync"
    assert text.count("Next:") == 1
    assert "Next: a2l sync" in text
    assert "all clear" in text


def test_every_next_command_names_a_registered_cli_command() -> None:
    """Doctor recovery output cannot route a user to a command the CLI does not expose."""
    from click import Group
    from typer.main import get_command
    from typer.testing import CliRunner

    from agent2learn.cli import app

    registered = set(cast(Group, get_command(app)).commands)
    assert set(doctor._REGISTERED_CLI_COMMANDS) <= registered
    scenarios = [
        [doctor.Check("Environment", "healthy", "ok", "fine")],
        [doctor.Check("Environment", "init", "fail", "missing", "run: a2l init")],
        [doctor.Check("Session", "auth", "fail", "expired", "run: a2l auth")],
        [
            doctor.Check(
                "Optional tools",
                "browser",
                "warn",
                "missing",
                "browser sign-in needs one; a2l auth --paste works without it",
            )
        ],
        [doctor.Check("Skills", "skills", "warn", "stale", "run: a2l skills install")],
        [doctor.Check("Filesystem", "unknown", "fail", "blocked", "run: a2l not-a-command")],
        [doctor.Check("Filesystem", "permissions", "fail", "blocked", "check permissions")],
    ]

    for checks in scenarios:
        action = doctor.next_command(checks)
        assert action is not None
        words = action.removeprefix("run: ").split()
        assert words[0] == "a2l", action
        assert words[1] in registered, action
        help_result = CliRunner().invoke(app, [words[1], "--help"])
        assert help_result.exit_code == 0, action


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


def test_session_checks_probe_api_versions_and_whoami_with_supplied_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)
    monkeypatch.setattr(doctor.session_module, "load", lambda: _session(hours_old=1))
    client = _DoctorClient(
        {
            "/d2l/api/versions/": [
                {"ProductCode": "lp", "LatestVersion": "1.62"},
                {"ProductCode": "le", "LatestVersion": "1.96"},
            ],
            "/d2l/api/lp/1.62/users/whoami": {"Identifier": "99999999"},
        }
    )

    checks = doctor.run_checks(_cfg(vault), vault, client=client)

    assert client.calls == [
        "/d2l/api/versions/",
        "/d2l/api/lp/1.62/users/whoami",
    ]
    assert next(c for c in checks if c.name == "session.api_versions").status == "ok"
    assert next(c for c in checks if c.name == "session.whoami").status == "ok"
    assert "99999999" not in " ".join(c.detail for c in checks)


def test_session_api_failure_is_a_redacted_check_not_an_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)
    monkeypatch.setattr(doctor.session_module, "load", lambda: _session(hours_old=1))
    client = _DoctorClient({"/d2l/api/versions/": SessionExpired("cookie-value")})

    checks = doctor.run_checks(_cfg(vault), vault, client=client)

    versions = next(c for c in checks if c.name == "session.api_versions")
    whoami = next(c for c in checks if c.name == "session.whoami")
    assert versions.status == "fail"
    assert whoami.status == "fail"
    everything = " ".join(f"{c.detail} {c.fix or ''}" for c in checks)
    assert "cookie-value" not in everything


def test_malformed_session_storage_does_not_crash_doctor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)

    def malformed() -> None:
        raise ValueError("stored cookie-value is invalid")

    monkeypatch.setattr(doctor.session_module, "load", malformed)

    checks = doctor.run_checks(_cfg(vault), vault)

    present = next(c for c in checks if c.name == "session.present")
    assert present.status == "fail"
    assert "cookie-value" not in " ".join(f"{c.detail} {c.fix or ''}" for c in checks)


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


def test_vault_reports_terms_empty_twins_and_last_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)
    first = vault.root / "Fall 2026" / "COURSE101"
    second = vault.root / "Winter 2027" / "COURSE202"
    _content_map(
        first,
        [
            {**_row(1, "markdown_ready"), "path": "Fall 2026/COURSE101/content/one.md"},
            {**_row(2, "source_only"), "path": None},
        ],
    )
    _content_map(
        second,
        [{**_row(3, "markdown_ready"), "path": "Winter 2027/COURSE202/content/two.md"}],
    )
    (vault.root / "Fall 2026/COURSE101/content").mkdir(parents=True)
    (vault.root / "Fall 2026/COURSE101/content/one.md").write_text("", encoding="utf-8")
    (vault.root / "Winter 2027/COURSE202/content").mkdir(parents=True)
    (vault.root / "Winter 2027/COURSE202/content/two.md").write_text("ready", encoding="utf-8")
    (vault.root / ".a2l" / "snapshots").mkdir(parents=True)
    (vault.root / ".a2l" / "snapshots/20260825T120000Z.json").write_text(
        json.dumps({"created_at": "2026-08-25T12:00:00Z"}), encoding="utf-8"
    )
    monkeypatch.setattr(doctor.session_module, "load", lambda: None)

    checks = doctor.run_checks(_cfg(vault), vault)

    terms = next(c for c in checks if c.name == "vault.terms")
    empty = next(c for c in checks if c.name == "vault.empty_twins")
    last_sync = next(c for c in checks if c.name == "vault.last_sync")
    assert "Fall 2026" in terms.detail and "Winter 2027" in terms.detail
    assert "1/2" in terms.detail and "1/1" in terms.detail
    assert "0 conversion gap(s)" in terms.detail
    assert "1 empty twin(s)" in terms.detail
    assert empty.status == "warn"
    assert empty.detail == "1 empty markdown twin(s)"
    assert last_sync.status == "ok"
    assert "2026-08-25" in last_sync.detail


def test_vault_scan_keeps_valid_terms_when_one_map_is_not_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)
    bad_map = vault.root / "Fall 2026" / "BROKEN" / "_meta"
    bad_map.mkdir(parents=True)
    (bad_map / "content_map.json").write_bytes(b"{\xff")
    valid_course = vault.root / "Winter 2027" / "COURSE202"
    _content_map(valid_course, [_row(1, "markdown_ready")])
    monkeypatch.setattr(doctor.session_module, "load", lambda: None)

    checks = doctor.run_checks(_cfg(vault), vault)

    courses = next(check for check in checks if check.name == "vault.courses")
    terms = next(check for check in checks if check.name == "vault.terms")
    assert courses.status == "warn"
    assert courses.detail == "1 course(s), 1 topic(s), 1 unreadable content map(s)"
    assert "Winter 2027" in terms.detail


def test_vault_scan_discloses_unreadable_content_maps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)
    bad_map = vault.root / "Fall 2026" / "BROKEN" / "_meta"
    bad_map.mkdir(parents=True)
    (bad_map / "content_map.json").write_bytes(b"{\xff")
    valid_course = vault.root / "Winter 2027" / "COURSE202"
    _content_map(valid_course, [_row(1, "markdown_ready")])
    monkeypatch.setattr(doctor.session_module, "load", lambda: None)

    checks = doctor.run_checks(_cfg(vault), vault)

    courses = next(check for check in checks if check.name == "vault.courses")
    assert courses.status == "warn"
    assert courses.detail == "1 course(s), 1 topic(s), 1 unreadable content map(s)"


def test_last_sync_discloses_unreadable_snapshot_alongside_valid_one(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    snapshots = vault.root / ".a2l" / "snapshots"
    snapshots.mkdir(parents=True)
    (snapshots / "valid.json").write_text(
        json.dumps({"created_at": "2026-08-25T12:00:00Z"}), encoding="utf-8"
    )
    (snapshots / "broken.json").write_bytes(b"{\xff")

    check = doctor._last_sync_check(vault)

    assert check.status == "warn"
    assert check.detail == "last sync 2026-08-25T12:00:00Z; 1 unreadable snapshot(s)"


def test_vault_with_only_unreadable_maps_is_not_called_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)
    bad_map = vault.root / "Fall 2026" / "BROKEN" / "_meta"
    bad_map.mkdir(parents=True)
    (bad_map / "content_map.json").write_bytes(b"{\xff")
    monkeypatch.setattr(doctor.session_module, "load", lambda: None)

    checks = doctor.run_checks(_cfg(vault), vault)

    present = next(check for check in checks if check.name == "vault.present")
    terms = next(check for check in checks if check.name == "vault.terms")
    assert present.detail == "vault has no readable courses; 1 unreadable content map(s)"
    assert terms.detail == "no readable term/course coverage; 1 unreadable content map(s)"


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


@pytest.mark.parametrize(
    "tracked, expected_status",
    [
        ("Fall 2026/C/discussions/post.md", "fail"),
        ("Fall 2026/C/assignments/Lab instructions/instructions.html", "warn"),
        ("Fall 2026/C/announcements/announcements.md", "warn"),
    ],
)
def test_git_tracking_classifies_all_private_and_course_material_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tracked: str,
    expected_status: str,
) -> None:
    vault = _vault(tmp_path)
    monkeypatch.setattr(doctor.session_module, "load", lambda: None)
    monkeypatch.setattr(doctor, "_inside_git_worktree", lambda root: True)
    monkeypatch.setattr(doctor, "_tracked_files", lambda root: [tracked])

    check = next(c for c in doctor.run_checks(_cfg(vault), vault) if c.name == "fs.git")

    assert check.status == expected_status


def test_malformed_git_index_fails_closed_without_disclosing_paths(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    git_directory = vault.root / ".git"
    git_directory.mkdir()
    raw = b"DIRC\x00\x00\x00\x02\x00\x00\x00\x01"
    (git_directory / "index").write_bytes(raw)

    check = doctor._git_tracking(vault)

    assert doctor._parse_git_index(raw, vault.root, vault.root) is None
    assert check.status == "fail"
    assert str(vault.root) not in check.detail
    assert str(vault.root) not in doctor.report([check])


def test_non_git_directory_remains_ok(tmp_path: Path) -> None:
    check = doctor._git_tracking(_vault(tmp_path))

    assert check.status == "ok"
    assert check.detail == "vault is not inside a Git repository"


def test_git_tracking_reads_a_linked_worktree_index(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    vault_root = repository / "vault"
    linked_git = tmp_path / "linked-git"
    vault_root.mkdir(parents=True)
    linked_git.mkdir()
    (repository / ".git").write_text("gitdir: ../linked-git\n", encoding="utf-8")

    name = b"vault/.a2l/private/session.json\x00"
    entry = b"\x00" * 62 + name
    entry += b"\x00" * ((-len(entry)) % 8)
    index = b"DIRC" + (2).to_bytes(4, "big") + (1).to_bytes(4, "big") + entry
    (linked_git / "index").write_bytes(index)

    check = doctor._git_tracking(Vault(vault_root))

    assert check.status == "fail"
    assert "private file" in check.detail


def _run_git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _force_v4_index(root: Path) -> bytes:
    _run_git(root, "update-index", "--index-version", "4")
    metadata = doctor._git_metadata(root)
    assert metadata is not None
    repository, git_directory = metadata
    raw = (git_directory / "index").read_bytes()
    assert raw[:8] == b"DIRC\x00\x00\x00\x04"
    assert doctor._parse_git_index(raw, root, repository) is None
    return raw


@pytest.mark.parametrize(
    ("tracked", "expected_status"),
    [
        (".a2l/private/pseudonym.key", "fail"),
        (".a2l/private/category-inventory.json", "fail"),
        (".a2l/submissions/receipt.json", "fail"),
        ("_meta/my_grades.json", "fail"),
        ("Fall 2026/Course/_meta/my_grades.json", "fail"),
        ("Fall 2026/Course/discussions/post.json", "fail"),
        ("notes/session-notes.pdf", "ok"),
    ],
)
def test_git_tracking_reads_private_paths_from_a_real_v4_index(
    tmp_path: Path, tracked: str, expected_status: str
) -> None:
    """Git v4 falls back safely, while exact names avoid session-notes false positives."""
    vault = tmp_path / "vault"
    vault.mkdir()
    _run_git(vault, "init")
    target = vault / tracked
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("synthetic\n", encoding="utf-8")
    _run_git(vault, "add", "--", tracked)
    _force_v4_index(vault)

    check = doctor._git_tracking(Vault(vault))

    assert check.status == expected_status
    assert tracked not in check.detail


def test_real_v4_index_invokes_the_bounded_git_ls_files_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _run_git(vault, "init")
    private = vault / ".a2l/private/pseudonym.key"
    private.parent.mkdir(parents=True)
    private.write_text("synthetic\n", encoding="utf-8")
    _run_git(vault, "add", "--", ".a2l/private/pseudonym.key")
    _force_v4_index(vault)
    real_run = subprocess.run
    calls: list[tuple[list[str], dict[str, object]]] = []

    def record_run(
        command: list[str],
        *,
        stdin: int | IO[Any] | None = None,
        stdout: int | IO[Any] | None = None,
        stderr: int | IO[Any] | None = None,
        check: bool = False,
        shell: bool = False,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        command_list = command
        kwargs: dict[str, object] = {
            "stdin": stdin,
            "stdout": stdout,
            "stderr": stderr,
            "check": check,
            "shell": shell,
            "timeout": timeout,
        }
        calls.append((command_list, kwargs))
        return real_run(
            command_list,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            check=check,
            shell=shell,
            timeout=timeout,
        )

    monkeypatch.setattr(doctor.subprocess, "run", record_run)

    tracked = doctor._tracked_files(vault)

    assert tracked == [".a2l/private/pseudonym.key"]
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[0] == "git"
    assert command[2:] == [os.fspath(doctor.paths.long_path(vault)), "ls-files", "-z", "--"]
    assert kwargs == {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL,
        "check": False,
        "shell": False,
        "timeout": 5,
    }


def test_real_v4_index_without_git_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _run_git(vault, "init")
    private = vault / ".a2l/private/pseudonym.key"
    private.parent.mkdir(parents=True)
    private.write_text("synthetic\n", encoding="utf-8")
    _run_git(vault, "add", "--", ".a2l/private/pseudonym.key")
    _force_v4_index(vault)

    def missing_git(*_args: object, **_kwargs: object) -> object:
        raise FileNotFoundError("/private/student/bin/git")

    monkeypatch.setattr(doctor.subprocess, "run", missing_git)

    check = doctor._git_tracking(Vault(vault))

    assert check.status == "fail"
    assert ".a2l/private/pseudonym.key" not in check.detail
    assert "/private/student" not in check.detail


def test_git_tracking_reads_a_private_file_through_a_linked_worktree_gitfile(
    tmp_path: Path,
) -> None:
    """A .git file points at the worktree index just as Git itself does."""
    vault = tmp_path / "vault"
    git_directory = tmp_path / "worktree-git"
    vault.mkdir()
    _run_git(vault, "init", f"--separate-git-dir={git_directory}")
    private = vault / ".a2l/private/pseudonym.key"
    private.parent.mkdir(parents=True)
    private.write_text("synthetic\n", encoding="utf-8")
    _run_git(vault, "add", "--", ".a2l/private/pseudonym.key")
    _force_v4_index(vault)

    check = doctor._git_tracking(Vault(vault))

    assert (vault / ".git").is_file()
    assert check.status == "fail"
    assert ".a2l/private/pseudonym.key" not in check.detail


def test_unreadable_git_metadata_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)

    def unreadable(_root: Path) -> tuple[Path, Path] | None:
        raise OSError("synthetic permission failure at /private/student/repository")

    monkeypatch.setattr(doctor, "_git_metadata", unreadable)

    check = doctor._git_tracking(vault)

    assert check.status == "fail"
    assert check.detail == "Git metadata is unreadable"
    assert "/private/student/repository" not in check.detail


def test_unreadable_git_index_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _vault(tmp_path)
    git_directory = vault.root / ".git"
    git_directory.mkdir()
    index = git_directory / "index"
    index.write_bytes(b"DIRC")
    real_open = open

    def deny_index(path: object, *args: object, **kwargs: object) -> object:
        if str(path).replace("\\", "/").endswith("/.git/index"):
            raise PermissionError("denied /private/student/repository/.git/index")
        return real_open(path, *args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr("builtins.open", deny_index)

    check = doctor._git_tracking(vault)

    assert check.status == "fail"
    assert check.detail == "inside Git, but the file list is unreadable"
    assert "/private/student" not in check.detail


def test_longest_path_permission_error_becomes_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "vault"
    root.mkdir()

    def denied(_root: Path) -> list[Path]:
        raise OSError("permission denied")

    monkeypatch.setattr(doctor.paths, "walk", denied)

    check = doctor._longest_path(root)

    assert check.status == "warn"
    assert "unavailable" in check.detail


def test_open_notice_names_the_destination_before_anything_leaves_the_device() -> None:
    checks = [doctor.Check("Environment", "env.version", "ok", "agent2learn 0.1.0")]

    notice = doctor.open_notice(checks)

    assert doctor.ISSUE_URL in notice
    assert "Opening this page sends the displayed redacted body to GitHub" in notice
    # The exact body is shown first, so consent is informed rather than implied.
    assert doctor.report(checks).strip() in notice


def test_issue_url_is_encoded_and_bounded() -> None:
    checks = [doctor.Check("Vault", f"check.{index}", "warn", "x") for index in range(4000)]

    url = doctor.issue_url(checks)

    assert url.startswith(doctor.ISSUE_URL)
    assert " " not in url and "\n" not in url
    assert len(url) < 40_000


def test_issue_url_hard_bounds_hostile_encoding_at_unicode_line_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile_token = "界" * 500
    monkeypatch.setattr(doctor, "__version__", hostile_token)
    monkeypatch.setattr(doctor.platform, "python_version", lambda: hostile_token)
    monkeypatch.setattr(doctor.platform, "system", lambda: hostile_token)
    monkeypatch.setattr(doctor.platform, "machine", lambda: hostile_token)
    secret = "/Users/student/private/session.json?token=super-secret"
    checks = [
        doctor.Check("Filesystem", "fs.git", "fail", secret, public=secret),
        *(doctor.Check("Vault", f"check.{index}", "warn", "x") for index in range(4000)),
    ]
    full_diagnostics = doctor.report(checks)

    url = doctor.issue_url(checks)
    query = parse_qs(urlsplit(url).query, strict_parsing=True)
    diagnostics = query["diagnostics"][0]

    assert len(url) <= 8_000
    assert query["template"] == ["bug_report.yml"]
    assert query["labels"] == ["bug"]
    assert "body" not in query
    assert diagnostics.endswith("_(truncated)_\n")
    complete_lines = diagnostics.removesuffix("_(truncated)_\n")
    assert complete_lines.endswith("\n")
    assert full_diagnostics.startswith(complete_lines)
    assert "界" * 64 in diagnostics
    assert secret not in diagnostics
    assert all(
        len(segment) >= 2 and all(char in "0123456789abcdefABCDEF" for char in segment[:2])
        for segment in url.split("%")[1:]
    )


def test_issue_url_prefills_the_bug_template_diagnostics_field_without_secrets() -> None:
    checks = [
        doctor.Check(
            "Filesystem",
            "fs.git",
            "fail",
            "private /Users/student/vault/.a2l/session.json token=super-secret",
            "remove it",
            public="private /Users/student/vault/.a2l/session.json token=super-secret",
        )
    ]

    query = parse_qs(urlsplit(doctor.issue_url(checks)).query, strict_parsing=True)

    assert query == {
        "template": ["bug_report.yml"],
        "labels": ["bug"],
        "diagnostics": [doctor.report(checks)],
    }
    assert "body" not in query
    decoded = query["diagnostics"][0]
    for secret in ("/Users/student", "session.json", "super-secret", "token="):
        assert secret not in decoded


def test_run_checks_never_raises_on_a_missing_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    """A diagnostic that crashes on a broken machine is worse than useless."""
    monkeypatch.setattr(doctor.session_module, "load", lambda: None)

    checks = doctor.run_checks(config_module.Config(vault=Path("/nonexistent/a2l")), None)

    assert doctor.exit_code(checks) in {1, 2}
    assert doctor.next_command(checks) is not None
