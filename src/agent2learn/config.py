"""Platform-correct machine configuration and state locations.

The config file is intentionally small and local. Known fields are validated strictly, while
unknown top-level JSON fields are retained as opaque future-version data and never interpreted by
this version. This permits a downgrade without silently deleting newer settings.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeAlias, cast

from platformdirs import PlatformDirs

from agent2learn import paths

JSONValue: TypeAlias = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]

DIRS = PlatformDirs("agent2learn", appauthor=False, ensure_exists=True)
DEFAULT_VAULT = Path.home() / "agent2learn"
_KNOWN_KEYS = frozenset(
    {
        "vault",
        "school",
        "submit_enabled",
        "include_discussions",
        "include_grades",
        "ocr_words_per_page",
    }
)


@dataclass(frozen=True)
class Config:
    """The user-controlled Agent2Learn configuration.

    ``submit_enabled`` is only the first acknowledgement gate; it is never sufficient to perform
    a submission. A fresh interactive confirmation remains mandatory for every file.
    """

    vault: Path = field(default_factory=lambda: DEFAULT_VAULT)
    school: str = "uwaterloo"
    submit_enabled: bool = False
    include_discussions: bool = False
    include_grades: bool = False
    ocr_words_per_page: int = 80
    extras: dict[str, JSONValue] = field(default_factory=dict)


def config_path() -> Path:
    """Return the per-user JSON config path and ensure its directory exists."""

    return _directory(DIRS.user_config_path) / "config.json"


def state_dir() -> Path:
    """Return the machine-state directory for sessions and calibration."""

    return _directory(DIRS.user_state_path)


def data_dir() -> Path:
    """Return the per-user data directory used for the dedicated browser profile."""

    return _directory(DIRS.user_data_path)


def log_path() -> Path:
    """Return the primary bounded local log path."""

    return _directory(DIRS.user_log_path) / "a2l.log"


def load() -> Config:
    """Load and validate config, returning privacy-safe defaults when it is absent."""

    destination = config_path()
    if not destination.is_file():
        return Config()

    try:
        with open(
            os.fspath(paths.long_path(destination)),
            encoding="utf-8",
            newline="",
        ) as handle:
            raw: Any = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError("config file is not valid JSON") from exc

    if not isinstance(raw, dict):
        raise ValueError("config root must be a JSON object")

    data: dict[str, JSONValue] = {
        cast(str, key): cast(JSONValue, value) for key, value in raw.items()
    }
    vault = _read_vault(data)
    school = _read_string(data, "school", "uwaterloo")
    submit_enabled = _read_bool(data, "submit_enabled", False)
    include_discussions = _read_bool(data, "include_discussions", False)
    include_grades = _read_bool(data, "include_grades", False)
    ocr_words_per_page = _read_positive_int(data, "ocr_words_per_page", 80)
    extras = {key: value for key, value in data.items() if key not in _KNOWN_KEYS}
    return Config(
        vault=vault,
        school=school,
        submit_enabled=submit_enabled,
        include_discussions=include_discussions,
        include_grades=include_grades,
        ocr_words_per_page=ocr_words_per_page,
        extras=extras,
    )


def save(cfg: Config) -> None:
    """Canonicalize and atomically save ``cfg`` through the shared path primitive."""

    if cfg.extras.keys() & _KNOWN_KEYS:
        raise ValueError("extras cannot replace a known config key")
    if not cfg.school:
        raise ValueError("school must not be empty")

    payload: dict[str, JSONValue] = {
        "include_discussions": cfg.include_discussions,
        "include_grades": cfg.include_grades,
        "ocr_words_per_page": cfg.ocr_words_per_page,
        "school": cfg.school,
        "submit_enabled": cfg.submit_enabled,
        "vault": os.fspath(cfg.vault),
        **cfg.extras,
    }
    text = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
        )
        + "\n"
    )
    destination = config_path()
    paths.atomic_write_text(destination, text)


def _directory(value: str | os.PathLike[str]) -> Path:
    directory = Path(value)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _read_vault(data: dict[str, JSONValue]) -> Path:
    value = data.get("vault", os.fspath(DEFAULT_VAULT))
    if not isinstance(value, str) or not value:
        raise ValueError("vault must be a non-empty string")
    return Path(value).expanduser()


def _read_string(data: dict[str, JSONValue], key: str, default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _read_bool(data: dict[str, JSONValue], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _read_positive_int(data: dict[str, JSONValue], key: str, default: int) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{key} must be a positive integer")
    return value


__all__ = [
    "DIRS",
    "DEFAULT_VAULT",
    "Config",
    "config_path",
    "data_dir",
    "load",
    "log_path",
    "save",
    "state_dir",
]
