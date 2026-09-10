import pytest

from reporter import config


REQUIRED = {
    "STEAM_API_KEY": "steam",
    "COMMAND_BOT_TOKEN": "bot",
    "USER_TOKEN": "user",
    "TARGET_GUILD_ID": 1,
    "TARGET_CHANNEL_ID": 2,
    "TICKET_MESSAGE_ID": 3,
    "TICKET_BUTTON_CUSTOM_ID": "button",
}


def set_required(monkeypatch, **overrides):
    values = REQUIRED | overrides
    for name, value in values.items():
        monkeypatch.setattr(config, name, value)


def test_validate_config_accepts_complete_configuration(monkeypatch):
    set_required(monkeypatch)
    config.validate_config()


def test_validate_config_lists_all_missing_or_invalid_keys(monkeypatch):
    set_required(
        monkeypatch,
        STEAM_API_KEY="",
        USER_TOKEN="   ",
        TARGET_GUILD_ID=0,
        TARGET_CHANNEL_ID=-1,
    )

    with pytest.raises(config.ConfigError) as excinfo:
        config.validate_config()

    message = str(excinfo.value)
    for name in (
        "STEAM_API_KEY",
        "USER_TOKEN",
        "TARGET_GUILD_ID",
        "TARGET_CHANNEL_ID",
    ):
        assert name in message
    assert "steam" not in message
    assert "user" not in message


def test_env_int_returns_zero_for_missing_or_malformed_values(monkeypatch):
    monkeypatch.delenv("TEST_ID", raising=False)
    assert config._env_int("TEST_ID") == 0
    monkeypatch.setenv("TEST_ID", "not-a-number")
    assert config._env_int("TEST_ID") == 0
    monkeypatch.setenv("TEST_ID", "42")
    assert config._env_int("TEST_ID") == 42
