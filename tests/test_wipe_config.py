from pathlib import Path

import pytest

from reporter.config import ConfigError, load_wipe_config, wipe_state_path


KEYS = ("WIPE_GUILD_ID", "WIPE_CHANNEL_ID", "WIPE_ADMIN_CHANNEL_ID")


def test_wipe_config_disabled_when_all_ids_are_blank(monkeypatch):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    assert load_wipe_config() is None


def test_partial_wipe_config_names_invalid_keys(monkeypatch):
    monkeypatch.setenv("WIPE_GUILD_ID", "7")
    monkeypatch.setenv("WIPE_CHANNEL_ID", "0")
    monkeypatch.delenv("WIPE_ADMIN_CHANNEL_ID", raising=False)
    with pytest.raises(ConfigError, match="WIPE_CHANNEL_ID.*WIPE_ADMIN_CHANNEL_ID"):
        load_wipe_config()


def test_valid_wipe_config_parses_three_ids(monkeypatch):
    monkeypatch.setenv("WIPE_GUILD_ID", "7")
    monkeypatch.setenv("WIPE_CHANNEL_ID", "8")
    monkeypatch.setenv("WIPE_ADMIN_CHANNEL_ID", "9")
    settings = load_wipe_config()
    assert (settings.guild_id, settings.channel_id, settings.admin_channel_id) == (7, 8, 9)


def test_wipe_state_path_prefers_systemd_directory(monkeypatch):
    monkeypatch.delenv("WIPE_STATE_PATH", raising=False)
    monkeypatch.setenv("STATE_DIRECTORY", "/var/lib/reportingbot")
    assert wipe_state_path() == Path("/var/lib/reportingbot/wipe_alerts.sqlite3")


def test_explicit_state_path_overrides_systemd(monkeypatch, tmp_path):
    target = tmp_path / "alerts.sqlite3"
    monkeypatch.setenv("STATE_DIRECTORY", "/var/lib/reportingbot")
    monkeypatch.setenv("WIPE_STATE_PATH", str(target))
    assert wipe_state_path() == target
