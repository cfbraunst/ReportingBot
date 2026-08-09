"""Central config. Everything secret comes from .env, never from source."""
import os
from dotenv import load_dotenv

load_dotenv()

STEAM_API_KEY = os.getenv("STEAM_API_KEY", "")
COMMAND_BOT_TOKEN = os.getenv("COMMAND_BOT_TOKEN", "")
USER_TOKEN = os.getenv("USER_TOKEN", "")

TARGET_GUILD_ID = int(os.getenv("TARGET_GUILD_ID") or 0)
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID") or 0)
TICKET_MESSAGE_ID = int(os.getenv("TICKET_MESSAGE_ID") or 0)
TICKET_BUTTON_CUSTOM_ID = os.getenv("TICKET_BUTTON_CUSTOM_ID", "")

# The four presets, exactly as given. Two communities: Rustoria and Rustopia.
SERVER_CHOICES = [
    "Rustoria EU Long",
    "Rustoria EU Medium",
    "Rustopia EU Large",
    "Rustopia EU Medium",
]
CUSTOM_SERVER_SENTINEL = "Custom"

# Always-constant report field.
REPORT_REASON = "Cheating/Ban Evading"

# Pacing. These exist to keep the user account from looking scripted.
MIN_DELAY_SECONDS = 4
MAX_DELAY_SECONDS = 15
MAX_REPORTS_PER_HOUR = 10
