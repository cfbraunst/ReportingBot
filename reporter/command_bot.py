"""The /report slash command. Runs as an ordinary bot in your own server.

Does no reporting itself -- it validates, resolves the Steam name, and hands a
job to the queue. The reporter picks it up from there.
"""
import asyncio
import logging

import discord
from discord import app_commands

from reporter.config import SERVER_CHOICES, CUSTOM_SERVER_SENTINEL
from reporter.jobs import ReportJob, queue
from reporter.steam import lookup, SteamIdError, SteamLookupError

log = logging.getLogger(__name__)

# The four presets plus Custom. Discord caps choices at 25, so this is safe.
_CHOICES = [app_commands.Choice(name=s, value=s) for s in SERVER_CHOICES]
_CHOICES.append(app_commands.Choice(name="Custom (type it below)", value=CUSTOM_SERVER_SENTINEL))


class CommandBot(discord.Client):
    def __init__(self) -> None:
        # No privileged intents needed: slash commands arrive as interactions,
        # so the bot never reads message content.
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        self.tree.add_command(report)
        await self.tree.sync()
        log.info("Slash commands synced.")

    async def on_ready(self) -> None:
        log.info("Command bot online as %s", self.user)


async def enqueue_or_reject(
    interaction: discord.Interaction, job: ReportJob
) -> int | None:
    """Enqueue without blocking; tell the caller when there is no room.

    Returns the new queue position, or None if the job was rejected and the
    user has already been told.
    """
    try:
        queue.put_nowait(job)
    except asyncio.QueueFull:
        await interaction.followup.send(
            "⏳ The report queue is full. Try again after an earlier report finishes."
        )
        return None
    return queue.qsize()


@app_commands.command(name="report", description="File a cheater report from a Steam ID.")
@app_commands.describe(
    steam_id="SteamID64, profile URL, STEAM_0:... or [U:1:...]",
    server="Which server they were on",
    custom_server="Server name -- required only if you picked Custom",
)
@app_commands.choices(server=_CHOICES)
async def report(
    interaction: discord.Interaction,
    steam_id: str,
    server: app_commands.Choice[str],
    custom_server: str | None = None,
) -> None:
    # Custom demands a value; Discord can't enforce that conditionally, so we do.
    if server.value == CUSTOM_SERVER_SENTINEL:
        if not custom_server or not custom_server.strip():
            await interaction.response.send_message(
                "You picked **Custom** but left `custom_server` empty. "
                "Re-run with the server name filled in.",
                ephemeral=True,
            )
            return
        server_name = custom_server.strip()
    else:
        server_name = server.value

    # Steam lookup can take a moment -- defer so the interaction doesn't expire.
    await interaction.response.defer(thinking=True)

    try:
        steam_id64, steam_name = await lookup(steam_id)
    except SteamIdError as e:
        await interaction.followup.send(f"❌ {e}")
        return
    except SteamLookupError as e:
        await interaction.followup.send(f"❌ {e}")
        return
    except Exception:
        log.exception("Steam lookup failed unexpectedly")
        await interaction.followup.send("❌ Couldn't reach Steam. Try again shortly.")
        return

    job = ReportJob(
        steam_id64=steam_id64,
        steam_name=steam_name,
        server_name=server_name,
        requester_id=interaction.user.id,
        channel_id=interaction.channel_id or 0,
    )

    position = await enqueue_or_reject(interaction, job)
    if position is None:
        return

    await interaction.followup.send(
        f"📋 Queued report for **{steam_name}** (`{steam_id64}`) on **{server_name}**.\n"
        f"-# Position in queue: {position} · you'll get a confirmation when it's filed."
    )
