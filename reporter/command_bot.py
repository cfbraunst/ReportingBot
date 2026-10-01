"""The /report slash command. Runs as an ordinary bot in your own server.

Does no reporting itself -- it validates, resolves the Steam name, and hands a
job to the queue. The reporter picks it up from there.
"""
import asyncio
import logging
import sqlite3
from pathlib import Path

import discord
from discord import app_commands

from reporter.config import SERVER_CHOICES, CUSTOM_SERVER_SENTINEL, WipeConfig, wipe_state_path
from reporter.jobs import ReportJob, queue
from reporter.steam import lookup, SteamIdError, SteamLookupError
from reporter.wipe_monitor import WipeMonitor, WipeMonitorError
from reporter.wipe_reactions import OPTIONS
from reporter.wipe_state import AlertStore

log = logging.getLogger(__name__)

# Presets from SERVER_CHOICES plus Custom. validate_config caps the presets at 24.
_CHOICES = [app_commands.Choice(name=s, value=s) for s in SERVER_CHOICES]
_CHOICES.append(app_commands.Choice(name="Custom (type it below)", value=CUSTOM_SERVER_SENTINEL))


class CommandBot(discord.Client):
    def __init__(
        self, wipe_config: WipeConfig | None = None, state_path: Path | None = None
    ) -> None:
        # Reaction events do not require the privileged Message Content intent.
        intents = discord.Intents.default()
        intents.reactions = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.wipe_monitor: WipeMonitor | None = None
        if wipe_config is not None:
            try:
                store = AlertStore(state_path or wipe_state_path())
                self.wipe_monitor = WipeMonitor(self, wipe_config, store)
            except (OSError, sqlite3.Error):
                log.exception("Wipe monitor state could not be opened")

    async def setup_hook(self) -> None:
        self.tree.add_command(report)
        self.tree.add_command(wipe_check)
        await self.tree.sync()
        log.info("Slash commands synced.")

    async def on_ready(self) -> None:
        log.info("Command bot online as %s", self.user)
        if self.wipe_monitor is not None:
            try:
                await self.wipe_monitor.startup_check()
            except (discord.HTTPException, OSError, sqlite3.Error, WipeMonitorError):
                log.exception("Startup wipe check failed")

    async def _wipe_event(self, payload, *, cleared: bool = False) -> None:
        if self.wipe_monitor is None:
            return
        try:
            if cleared:
                await self.wipe_monitor.reactions_cleared(payload)
            else:
                await self.wipe_monitor.reaction_changed(payload)
        except (discord.HTTPException, OSError, sqlite3.Error, WipeMonitorError):
            log.exception("Wipe reaction check failed")

    async def on_raw_reaction_add(self, payload) -> None:
        await self._wipe_event(payload)

    async def on_raw_reaction_remove(self, payload) -> None:
        await self._wipe_event(payload)

    async def on_raw_reaction_clear(self, payload) -> None:
        await self._wipe_event(payload, cleared=True)

    async def on_raw_reaction_clear_emoji(self, payload) -> None:
        await self._wipe_event(payload, cleared=True)


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


@app_commands.command(name="wipe-check", description="Check the latest wipe reactions")
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
async def wipe_check(interaction: discord.Interaction) -> None:
    permissions = getattr(interaction.user, "guild_permissions", None)
    if not permissions or not permissions.administrator:
        await interaction.response.send_message("Administrators only.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    monitor = getattr(interaction.client, "wipe_monitor", None)
    if monitor is None or interaction.guild_id != monitor.config.guild_id:
        await interaction.followup.send("Wipe checking is unavailable here.", ephemeral=True)
        return

    try:
        result = await monitor.check_latest()
    except (discord.HTTPException, OSError, sqlite3.Error, WipeMonitorError):
        log.exception("Wipe check failed")
        await interaction.followup.send("Could not finish the wipe check.", ephemeral=True)
        return

    if result is None:
        await interaction.followup.send(
            "No wipe message with all three reactions was found.", ephemeral=True
        )
        return

    message, overlaps = result
    lines = [
        f"<@{user_id}>: {' '.join(emoji for emoji in OPTIONS if emoji in choices)}"
        for user_id, choices in sorted(overlaps.items())
    ]
    current = f"Wipe message: {message.jump_url}\n"
    for line in lines or ["No one chose multiple options."]:
        if len(current) + len(line) + 1 > 1900:
            await interaction.followup.send(
                current, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )
            current = f"Continued: {message.jump_url}\n"
        current += line + "\n"
    await interaction.followup.send(
        current, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
    )


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
