"""Read-only discovery: find the ticket message and its button custom_id.

Logs in with USER_TOKEN, reads the last few messages in TARGET_CHANNEL_ID, and
prints every button it finds along with the message that carries it. Fill the
values it prints into TICKET_MESSAGE_ID and TICKET_BUTTON_CUSTOM_ID.

This script only reads. It never clicks a button, opens a form, or submits
anything. Run it before `main.py`, once per target.
"""
import asyncio
import logging
import sys

import selfcord
from selfcord.components import Button

from reporter.config import TARGET_CHANNEL_ID, TARGET_GUILD_ID, USER_TOKEN

logging.basicConfig(level=logging.WARNING, format="%(levelname)-7s %(message)s")

SCAN_LIMIT = 25


def _require_config() -> None:
    """Only the three values discovery itself needs -- the rest are its output."""
    missing = [
        name for name, value in (
            ("USER_TOKEN", USER_TOKEN),
            ("TARGET_GUILD_ID", TARGET_GUILD_ID),
            ("TARGET_CHANNEL_ID", TARGET_CHANNEL_ID),
        ) if not value
    ]
    if missing:
        raise SystemExit(
            "Set these in .env before running discovery: " + ", ".join(missing)
        )


class Discoverer(selfcord.Client):
    async def on_ready(self) -> None:
        print(f"Logged in as {self.user}. Scanning...\n")
        try:
            await self._scan()
        finally:
            await self.close()

    async def _scan(self) -> None:
        guild = self.get_guild(TARGET_GUILD_ID)
        if guild is None:
            print(f"Not a member of guild {TARGET_GUILD_ID}, or it is unreachable.")
            return

        channel = guild.get_channel(TARGET_CHANNEL_ID) or self.get_channel(TARGET_CHANNEL_ID)
        if channel is None:
            print(f"Channel {TARGET_CHANNEL_ID} is not visible to this account.")
            return

        print(f"Guild:   {guild.name} ({guild.id})")
        print(f"Channel: #{getattr(channel, 'name', '?')} ({channel.id})\n")

        found = 0
        async for message in channel.history(limit=SCAN_LIMIT):
            buttons = [
                c for row in message.components
                for c in getattr(row, "children", [])
                if isinstance(c, Button)
            ]
            if not buttons:
                continue
            found += len(buttons)
            print(f"TICKET_MESSAGE_ID={message.id}")
            print(f"  from {message.author} -- {len(buttons)} button(s):")
            for b in buttons:
                label = b.label or "(no label)"
                print(f"    TICKET_BUTTON_CUSTOM_ID={b.custom_id}    # {label!r}")
            print()

        if not found:
            print(
                f"No buttons in the last {SCAN_LIMIT} messages. Raise SCAN_LIMIT, or\n"
                "check that TARGET_CHANNEL_ID is the channel holding the button."
            )
            return

        print(
            "Copy the matching pair into .env. The form's own field custom_ids are\n"
            "hardcoded in reporter/reporter_client.py -- if your target's form differs\n"
            "from the one in README.md, update those constants too."
        )


def main() -> None:
    _require_config()
    client = Discoverer()
    try:
        asyncio.run(client.start(USER_TOKEN))
    except KeyboardInterrupt:
        pass
    except selfcord.LoginFailure:
        raise SystemExit("USER_TOKEN was rejected. It may have expired -- see SETUP.md.")


if __name__ == "__main__":
    sys.exit(main())
