"""Configuration, console, error, and local logging contracts."""

from __future__ import annotations

import io
import json
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from platformdirs import PlatformDirs

from agent2learn import __version__, config, console
from agent2learn.errors import A2LError, NotConfigured, SessionExpired


class _Stream(io.StringIO):
    def __init__(self, *, tty: bool, encoding: str) -> None:
        super().__init__()
        self._tty = tty
        self._encoding = encoding

    @property
    def encoding(self) -> str:
        return self._encoding

    def isatty(self) -> bool:
        return self._tty


def _temporary_dirs(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        user_config_path=root / "config" / "agent2learn",
        user_state_path=root / "state" / "agent2learn",
        user_data_path=root / "data" / "agent2learn",
        user_log_path=root / "logs" / "agent2learn",
    )


@pytest.fixture
def isolated_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    directories = _temporary_dirs(tmp_path)
    monkeypatch.setattr(config, "DIRS", directories)
    return directories


@pytest.fixture
def isolated_logs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    directories = _temporary_dirs(tmp_path)
    monkeypatch.setattr(config, "DIRS", directories)
    yield directories.user_log_path

    logger = console.get_logger()
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def test_default_config_is_private_by_default(isolated_dirs: SimpleNamespace) -> None:
    cfg = config.load()

    assert cfg.vault == Path.home() / "agent2learn"
    assert cfg.school == "uwaterloo"
    assert cfg.include_grades is False
    assert cfg.include_discussions is False
    assert cfg.submit_enabled is False
    assert cfg.ocr_words_per_page == 80
    assert cfg.extras == {}


def test_config_round_trips_paths_and_opt_in_categories(
    isolated_dirs: SimpleNamespace, tmp_path: Path
) -> None:
    expected = config.Config(
        vault=tmp_path / "my vault",
        school="uwaterloo",
        submit_enabled=True,
        include_discussions=True,
        include_grades=True,
        ocr_words_per_page=120,
    )

    config.save(expected)

    assert config.load() == expected
    assert config.config_path().read_text(encoding="utf-8").endswith("\n")


def test_config_preserves_unknown_future_keys(isolated_dirs: SimpleNamespace) -> None:
    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "vault": "/tmp/vault",
                "school": "uwaterloo",
                "future_flag": True,
                "future_options": {"mode": "careful", "retries": 2},
            }
        ),
        encoding="utf-8",
    )

    loaded = config.load()
    assert loaded.extras == {
        "future_flag": True,
        "future_options": {"mode": "careful", "retries": 2},
    }

    config.save(loaded)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["future_flag"] is True
    assert saved["future_options"] == {"mode": "careful", "retries": 2}


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("vault", 42),
        ("school", ["uwaterloo"]),
        ("submit_enabled", "yes"),
        ("include_discussions", 1),
        ("include_grades", None),
        ("ocr_words_per_page", 0),
    ],
)
def test_config_rejects_wrong_known_types(
    isolated_dirs: SimpleNamespace, key: str, value: object
) -> None:
    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({key: value}), encoding="utf-8")

    with pytest.raises(ValueError, match=key):
        config.load()


def test_config_rejects_non_object_json(isolated_dirs: SimpleNamespace) -> None:
    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="object"):
        config.load()


def test_config_rejects_invalid_json(isolated_dirs: SimpleNamespace) -> None:
    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="JSON"):
        config.load()


@pytest.mark.skipif(os.name == "nt", reason="file symlinks require Windows privileges")
def test_config_rejects_a_symlinked_file(isolated_dirs: SimpleNamespace, tmp_path: Path) -> None:
    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside-config.json"
    outside.write_text('{"submit_enabled": true}\n', encoding="utf-8")
    path.symlink_to(outside)

    with pytest.raises(ValueError, match="symlink"):
        config.load()

    assert outside.read_text(encoding="utf-8") == '{"submit_enabled": true}\n'


def test_config_rejects_malformed_utf8_as_invalid_json(isolated_dirs: SimpleNamespace) -> None:
    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"{\xff")

    with pytest.raises(ValueError, match="JSON"):
        config.load()


def test_config_does_not_treat_an_unreadable_file_as_defaults(
    isolated_dirs: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"submit_enabled": true}', encoding="utf-8")

    def denied(*args: object, **kwargs: object) -> object:
        raise PermissionError("config denied")

    monkeypatch.setattr(config, "open", denied, raising=False)

    with pytest.raises(ValueError, match="unreadable"):
        config.load()


def test_config_does_not_treat_a_denied_file_probe_as_absent(
    isolated_dirs: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"submit_enabled": true}', encoding="utf-8")

    def denied_probe(_path: Path) -> Path:
        raise PermissionError("config denied")

    monkeypatch.setattr(config, "config_path", lambda: path)
    monkeypatch.setattr(config.paths, "long_path", denied_probe)

    with pytest.raises(ValueError, match="unreadable"):
        config.load()


def test_config_save_routes_through_atomic_writer(
    isolated_dirs: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, str]] = []

    def record(destination: Path, text: str, *, retries: int = 5) -> None:
        calls.append((destination, text))

    monkeypatch.setattr(config.paths, "atomic_write_text", record)
    config.save(config.Config())

    assert len(calls) == 1
    assert calls[0][0] == config.config_path()
    assert json.loads(calls[0][1])["submit_enabled"] is False
    assert calls[0][1].endswith("\n")


def test_config_save_keeps_previous_file_when_atomic_install_fails(
    isolated_dirs: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = config.config_path()
    config.save(config.Config(vault=Path("/old")))
    previous = destination.read_bytes()

    def fail_replace(*args: object, **kwargs: object) -> None:
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(config.paths.os, "replace", fail_replace)
    monkeypatch.setattr(config.paths.time, "sleep", lambda _seconds: None)

    with pytest.raises(PermissionError):
        config.save(config.Config(vault=Path("/new")))

    assert destination.read_bytes() == previous
    assert not list(destination.parent.glob(".*.tmp"))


@pytest.mark.skipif(sys.platform != "linux", reason="XDG override is a Linux contract")
def test_xdg_config_home_relocates_config_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setattr(
        config,
        "DIRS",
        PlatformDirs("agent2learn", appauthor=False, ensure_exists=True),
    )

    assert config.config_path() == tmp_path / "xdg-config" / "agent2learn" / "config.json"


def test_platform_directories_keep_machine_state_out_of_the_vault(
    isolated_dirs: SimpleNamespace,
) -> None:
    assert config.state_dir() == isolated_dirs.user_state_path
    assert config.data_dir() == isolated_dirs.user_data_path
    assert config.log_path() == isolated_dirs.user_log_path / "a2l.log"
    assert config.config_path() == isolated_dirs.user_config_path / "config.json"


def test_error_taxonomy_has_stable_exit_codes() -> None:
    assert A2LError.exit_code == 1
    assert SessionExpired.exit_code == 75
    assert NotConfigured.exit_code == 3
    assert isinstance(SessionExpired("expired"), A2LError)


def test_ascii_glyphs_are_used_when_stream_cannot_encode_checkmark() -> None:
    stream = _Stream(tty=True, encoding="ascii")

    assert console._glyphs_for(stream) == {
        "ok": "[ok]",
        "warn": "[!]",
        "fail": "[x]",
        "info": "[-]",
    }


def test_unicode_glyphs_are_used_when_stream_supports_them() -> None:
    stream = _Stream(tty=True, encoding="utf-8")

    assert console._glyphs_for(stream) == {
        "ok": "✓",
        "warn": "⚠",
        "fail": "✗",
        "info": "ℹ",
    }


def test_console_disables_color_for_non_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _Stream(tty=False, encoding="utf-8")
    monkeypatch.setattr(console.sys, "stdout", stream)

    rich_console = console.out()
    rich_console.print("[red]hello[/red]")

    assert rich_console.is_terminal is False
    assert rich_console.no_color is True
    assert "\x1b[" not in stream.getvalue()


def test_console_honours_no_color_on_a_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _Stream(tty=True, encoding="utf-8")
    monkeypatch.setattr(console.sys, "stdout", stream)
    monkeypatch.setenv("NO_COLOR", "1")

    rich_console = console.out()

    assert rich_console.is_terminal is True
    assert rich_console.no_color is True


def test_rotating_log_handler_is_bounded_and_allowlisted(isolated_logs: Path) -> None:
    logger = console.configure_logging()
    handlers = [handler for handler in logger.handlers if isinstance(handler, logging.Handler)]

    assert len(handlers) == 1
    handler = handlers[0]
    assert handler.maxBytes == 1_048_576
    assert handler.backupCount == 4
    assert config.log_path() == isolated_logs / "a2l.log"


def test_logs_keep_only_structured_safe_fields_and_drop_sensitive_context(
    isolated_logs: Path,
) -> None:
    logger = console.configure_logging()
    sensitive = {
        "url": "https://learn.example.invalid/course?id=COURSE-123",
        "headers": "Authorization: Bearer cookie-token",
        "body": "raw response body with grade 97",
        "cookies": "d2lSessionVal=secret-cookie",
        "identity": "Student Identity",
        "course": "COURSE101",
        "filename": "final-draft.pdf",
        "grade": "grade: 97%",
        "discussion": "discussion by Student Identity",
        "draft": "draft answer text",
        "confirmation": "I CONFIRM UPLOAD ABC123 final-draft.pdf",
    }

    console.log_event(
        "sync_completed",
        diagnostic_code="SYNC_OK",
        stage_ms=123,
        status="success",
        exception=RuntimeError(" | ".join(sensitive.values())),
        **sensitive,
    )
    logger.warning(" | ".join(sensitive.values()))
    for handler in logger.handlers:
        handler.flush()

    text = config.log_path().read_text(encoding="utf-8")
    payload = json.loads(text)
    assert set(payload) <= {
        "event",
        "diagnostic_code",
        "stage_ms",
        "package_version",
        "status",
        "exception_class",
    }
    assert payload == {
        "diagnostic_code": "SYNC_OK",
        "event": "sync_completed",
        "exception_class": "RuntimeError",
        "package_version": __version__,
        "stage_ms": 123,
        "status": "success",
    }
    assert all(secret not in text for secret in sensitive.values())


@pytest.mark.parametrize("verbose", [False, True])
def test_verbose_logging_does_not_relax_the_data_allowlist(
    isolated_logs: Path, verbose: bool
) -> None:
    logger = console.configure_logging(verbose=verbose)
    secret = "https://learn.example.invalid/secret?token=COURSE101"  # pragma: allowlist secret
    console.log_event("sync", url=secret, body=secret, filename=secret)
    for handler in logger.handlers:
        handler.flush()

    assert secret not in config.log_path().read_text(encoding="utf-8")


def test_log_event_rejects_private_values_in_persisted_fields(isolated_logs: Path) -> None:
    console.configure_logging()

    with pytest.raises(ValueError):
        console.log_event("COURSE101")
    with pytest.raises(ValueError):
        console.log_event("sync", diagnostic_code="student-123")
    with pytest.raises(ValueError):
        console.log_event("sync", status="final-draft.pdf")

    class StudentException(RuntimeError):
        pass

    console.log_event("sync", exception=StudentException("private"))
    for handler in console.get_logger().handlers:
        handler.flush()

    text = config.log_path().read_text(encoding="utf-8")
    assert "StudentException" not in text


def test_logging_opens_the_log_through_the_long_path_boundary(
    isolated_logs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extended = isolated_logs / "extended" / "a2l.log"
    opened: list[object] = []

    class FakeHandler:
        def __init__(self, path: object, **_kwargs: object) -> None:
            opened.append(path)

        def setLevel(self, _level: int) -> None:
            return

        def setFormatter(self, _formatter: object) -> None:
            return

        def addFilter(self, _filter: object) -> None:
            return

        def close(self) -> None:
            return

    monkeypatch.setattr(console, "RotatingFileHandler", FakeHandler)
    monkeypatch.setattr(console.paths, "long_path", lambda _path: extended)

    console.configure_logging()

    assert opened == [os.fspath(extended)]
