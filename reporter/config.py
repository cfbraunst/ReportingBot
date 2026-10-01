"""Central config. Everything secret comes from .env, never from source."""
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class ConfigError(ValueError):
    """Required environment configuration is missing or invalid."""


@dataclass(frozen=True)
class WipeConfig:
    guild_id: int
    channel_id: int
    admin_channel_id: int


def load_wipe_config() -> WipeConfig | None:
    """Return optional wipe channels, or reject an incomplete configuration."""
    names = ("WIPE_GUILD_ID", "WIPE_CHANNEL_ID", "WIPE_ADMIN_CHANNEL_ID")
    raw = {name: os.getenv(name, "").strip() for name in names}
    if not any(raw.values()):
        return None
    invalid = [name for name, value in raw.items() if not value.isdecimal() or int(value) <= 0]
    if invalid:
        raise ConfigError("Missing or invalid wipe configuration: " + ", ".join(invalid))
    return WipeConfig(*(int(raw[name]) for name in names))


def wipe_state_path() -> Path:
    """Use managed systemd storage in production and a local path otherwise."""
    override = os.getenv("WIPE_STATE_PATH", "").strip()
    if override:
        return Path(override)
    directory = os.getenv("STATE_DIRECTORY", "").strip()
    return Path(directory or "data") / "wipe_alerts.sqlite3"


def _env_int(name: str) -> int:
    try:
        return int(os.getenv(name) or 0)
    except ValueError:
        return 0


STEAM_API_KEY = os.getenv("STEAM_API_KEY", "")
COMMAND_BOT_TOKEN = os.getenv("COMMAND_BOT_TOKEN", "")
USER_TOKEN = os.getenv("USER_TOKEN", "")

TARGET_GUILD_ID = _env_int("TARGET_GUILD_ID")
TARGET_CHANNEL_ID = _env_int("TARGET_CHANNEL_ID")
TICKET_MESSAGE_ID = _env_int("TICKET_MESSAGE_ID")
TICKET_BUTTON_CUSTOM_ID = os.getenv("TICKET_BUTTON_CUSTOM_ID", "")

# Discord allows 25 choices per option; one of them is always Custom.
MAX_SERVER_CHOICES = 24


def _server_choices() -> list[str]:
    """Dropdown presets for /report, comma-separated in SERVER_CHOICES."""
    names = (name.strip() for name in os.getenv("SERVER_CHOICES", "").split(","))
    return list(dict.fromkeys(name for name in names if name))


SERVER_CHOICES = _server_choices()
CUSTOM_SERVER_SENTINEL = "Custom"

# Always-constant report field.
REPORT_REASON = "Cheating/Ban Evading"

# Master switch. While false, the reporter opens and fills the form but never
# submits -- the full path runs with nothing filed. Flip deliberately.
LIVE_SUBMIT = os.getenv("LIVE_SUBMIT", "false").strip().lower() in ("1", "true", "yes")

# Pacing. These exist to keep the user account from looking scripted.
#
# The per-minute limit is enforced as a minimum gap plus jitter, never a fixed
# 60s tick -- perfectly regular timing is itself the thing that looks automated.
MIN_SECONDS_BETWEEN_REPORTS = 60
MIN_DELAY_SECONDS = 4    # extra jitter added on top of the gap
MAX_DELAY_SECONDS = 35
MAX_REPORTS_PER_HOUR = 5


def _is_unset(value: object) -> bool:
    """IDs must be positive; text must be more than whitespace."""
    if isinstance(value, int):
        return value <= 0
    return not str(value).strip()


def validate_config() -> None:
    """Raise ConfigError naming every required key that is missing or invalid.

    The message carries key names only -- never their values, which are secret.
    """
    values = {
        "STEAM_API_KEY": STEAM_API_KEY,
        "COMMAND_BOT_TOKEN": COMMAND_BOT_TOKEN,
        "USER_TOKEN": USER_TOKEN,
        "TARGET_GUILD_ID": TARGET_GUILD_ID,
        "TARGET_CHANNEL_ID": TARGET_CHANNEL_ID,
        "TICKET_MESSAGE_ID": TICKET_MESSAGE_ID,
        "TICKET_BUTTON_CUSTOM_ID": TICKET_BUTTON_CUSTOM_ID,
    }
    invalid = sorted(name for name, value in values.items() if _is_unset(value))
    if len(SERVER_CHOICES) > MAX_SERVER_CHOICES:
        invalid.append(f"SERVER_CHOICES (at most {MAX_SERVER_CHOICES} names)")
    if invalid:
        raise ConfigError(
            "Missing or invalid required configuration: " + ", ".join(invalid)
        )
