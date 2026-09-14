"""Exercise the real suite fixtures behind synthetic host-state and network sentinels.

The child process installs these sentinels *before* pytest loads the copied conftest. Thus even
removing every isolation fixture can only damage temporary synthetic state, never user data.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_BOOTSTRAP = r"""
import json
import socket
from pathlib import Path
from types import SimpleNamespace

import keyring.core
import pytest
from keyring.backend import KeyringBackend
from agent2learn import config, session

host = Path.cwd() / "synthetic-host"
host.mkdir()
config.DIRS = SimpleNamespace(**{
    "user_" + name + "_path": host / name
    for name in ("config", "state", "data", "log")
})
config.DEFAULT_VAULT = host / "home" / "agent2learn"
Path.home = classmethod(lambda cls: host / "home")
config.save(config.Config(extras={"host_sentinel": True}))
state = config.state_dir()
(state / "session.json").write_text("synthetic host session\n", encoding="utf-8")
(state / "calibration.json").write_text("{}\n", encoding="utf-8")
profile = config.data_dir() / "browser-profile"
profile.mkdir()
(profile / "sentinel").write_text("synthetic host profile\n", encoding="utf-8")

class HostKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        pass

    def get_password(self, service, username):
        if service == "agent2learn":
            return json.dumps({
                "base_url": "https://learn.example.invalid", "cookies": [], "xsrf": None,
                "harvested_at": "2026-01-01T00:00:00Z", "user_id": None,
            })
        return "synthetic host credential"

    def set_password(self, service, username, password):
        (host / "keyring-touched").touch()

    def delete_password(self, service, username):
        (host / "keyring-touched").touch()

keyring.core.set_keyring(HostKeyring())
session._last_backend = "synthetic-host-cache"

# No real connect or DNS lookup is possible even when the suite guard is absent/broken.
socket.socket.connect = lambda *_args, **_kwargs: None
socket.socket.connect_ex = lambda *_args, **_kwargs: 0
socket.getaddrinfo = lambda *_args, **_kwargs: []

raise SystemExit(pytest.main([
    "-q", "--tb=short", "-p", "no:cacheprovider",
    "--basetemp", str(Path.cwd() / "probe-tmp"), "test_probe.py",
]))
"""

_PROBES = r"""
import io
import json
import socket
from datetime import UTC, datetime
from pathlib import Path

import keyring
import pytest
from agent2learn import auth, config, session
from agent2learn.calibrate import calibrate

HOST = Path(__file__).parent / "synthetic-host"


@pytest.mark.parametrize("getter", ["config_path", "state_dir", "data_dir", "log_path"])
def test_machine_paths_are_per_test(getter, tmp_path):
    assert getattr(config, getter)().is_relative_to(tmp_path)


def test_default_vault_and_home_are_per_test(tmp_path):
    assert config.Config().vault.is_relative_to(tmp_path)
    assert config.Config().vault == Path.home() / "agent2learn"
    assert Path("~").expanduser() == Path.home()


def test_config_round_trip_does_not_read_or_replace_host_config(tmp_path):
    assert config.load().extras == {}
    config.save(config.Config(vault=tmp_path / "chosen-vault"))
    assert config.load().vault == tmp_path / "chosen-vault"
    assert json.loads((HOST / "config/config.json").read_text())["host_sentinel"] is True


def test_real_calibration_does_not_replace_host_state(tmp_path):
    class Client:
        def get_json(self, path):
            if path.endswith("/versions/"):
                return [
                    {"ProductCode": "lp", "LatestVersion": "1.62"},
                    {"ProductCode": "le", "LatestVersion": "1.96"},
                ]
            if path.endswith("/whoami"):
                return {"Identifier": "synthetic-user"}
            return {"Items": [], "PagingInfo": {"HasMoreItems": False}}

    calibrate(Client())
    assert (HOST / "state/calibration.json").read_text() == "{}\n"
    assert (config.state_dir() / "calibration.json").is_relative_to(tmp_path)
    assert json.loads((config.state_dir() / "calibration.json").read_text())["courses"] == []


@pytest.mark.parametrize("direct_backend", [False, True])
def test_keyring_api_and_backend_are_memory_only(direct_backend):
    api = keyring.get_keyring() if direct_backend else keyring
    assert api.get_password("isolation", "user") is None
    api.set_password("isolation", "user", "synthetic-value")
    assert keyring.get_password("isolation", "user") == "synthetic-value"
    assert keyring.get_keyring().get_password("isolation", "user") == "synthetic-value"
    credential = keyring.get_credential("isolation", "user")
    assert credential is not None
    # This credential exists only in the test's in-memory backend.
    assert credential.password == "synthetic-value"  # pragma: allowlist secret
    assert api.get_password("another-service", "user") is None
    api.delete_password("isolation", "user")
    assert api.get_password("isolation", "user") is None
    assert not (HOST / "keyring-touched").exists()


def test_backend_cache_does_not_inherit_host_state():
    assert session._last_backend is None


def test_clear_profile_does_not_clear_host_session_or_profile(monkeypatch):
    class TTY(io.StringIO):
        def isatty(self):
            return True

    profile = config.data_dir() / "browser-profile"
    profile.mkdir(exist_ok=True)
    (profile / "test-profile").touch()
    monkeypatch.setattr(auth.sys, "stdin", TTY("yes\n"))
    monkeypatch.setattr(auth.sys, "stdout", TTY())
    monkeypatch.setattr(auth.sys, "stderr", TTY())
    auth.clear_profile()
    assert not profile.exists()
    assert (HOST / "state/session.json").is_file()
    assert (HOST / "data/browser-profile/sentinel").is_file()
    assert (HOST / "state/session.json").read_text() == "synthetic host session\n"
    assert (HOST / "data/browser-profile/sentinel").read_text() == "synthetic host profile\n"
    assert not (HOST / "keyring-touched").exists()


@pytest.mark.parametrize("iteration", [1, 2])
def test_each_test_starts_with_empty_storage_and_backend_cache(iteration):
    assert session._last_backend is None
    assert session.load() is None
    assert config.load().extras == {}
    assert not (config.state_dir() / "previous-test").exists()
    value = session.Session("https://learn.example.invalid", (), None, datetime.now(UTC), None)
    assert session.store(value) == "keyring"
    assert session.load() == value
    config.save(config.Config(extras={"previous_test": iteration}))
    (config.state_dir() / "previous-test").touch()


@pytest.mark.parametrize("method", ["connect", "connect_ex"])
def test_nonloopback_is_blocked_without_requesting_a_fixture(method):
    with socket.socket() as sock:
        with pytest.raises(RuntimeError, match="tests must be offline"):
            getattr(sock, method)(("198.51.100.1", 443))


def test_external_dns_is_blocked_before_resolution():
    with pytest.raises(RuntimeError, match="tests must be offline"):
        socket.getaddrinfo("learn.example.invalid", 443)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_remains_available(host):
    with socket.socket() as sock:
        assert sock.connect((host, 12345)) is None
        assert sock.connect_ex((host, 12345)) == 0
    assert socket.getaddrinfo(host, 12345) == []


def test_isolation_setup_itself_does_not_create_directories(tmp_path):
    assert list(tmp_path.iterdir()) == []
"""


def test_default_fixtures_protect_synthetic_host_state(tmp_path: Path) -> None:
    """Removing a default boundary must fail without ever reaching the real host boundary."""
    conftest = Path(__file__).with_name("conftest.py").read_text(encoding="utf-8")
    (tmp_path / "conftest.py").write_text(conftest, encoding="utf-8")
    (tmp_path / "test_probe.py").write_text(_PROBES, encoding="utf-8")
    environment = os.environ | {
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOME": str(tmp_path / "synthetic-home"),
        "USERPROFILE": str(tmp_path / "synthetic-home"),
    }
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", _BOOTSTRAP],
        cwd=tmp_path,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "20 passed" in result.stdout, result.stdout
    assert not (tmp_path / "synthetic-host/keyring-touched").exists()
