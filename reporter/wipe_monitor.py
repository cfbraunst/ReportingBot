"""Detect and alert on conflicting wipe attendance reactions."""

import asyncio

import discord

from reporter.config import WipeConfig
from reporter.wipe_reactions import OPTIONS, latest_eligible, overlaps_for_message
from reporter.wipe_state import AlertStore


class WipeMonitorError(Exception):
    """The configured wipe channels cannot be used."""


class WipeMonitor:
    def __init__(self, bot: discord.Client, config: WipeConfig, store: AlertStore):
        self.bot = bot
        self.config = config
        self.store = store
        self._locks: dict[int, asyncio.Lock] = {}

    async def reconcile_message(self, message: discord.Message) -> None:
        lock = self._locks.setdefault(message.id, asyncio.Lock())
        async with lock:
            await self._reconcile_locked(message)

    async def _reconcile_locked(self, message: discord.Message) -> None:
        current = await overlaps_for_message(message, self.bot.user.id)
        guild_id, message_id = self.config.guild_id, message.id
        if current is None:
            self.store.clear_message(guild_id, message_id)
            return

        sent = self.store.active_users(guild_id, message_id)
        self.store.clear_except(guild_id, message_id, set(current))
        for user_id, choices in current.items():
            if user_id in sent:
                continue
            admin = await self._channel(self.config.admin_channel_id)
            selected = " ".join(emoji for emoji in OPTIONS if emoji in choices)
            text = f"<@{user_id}> selected {selected} on {message.jump_url}"
            await admin.send(text, allowed_mentions=discord.AllowedMentions.none())
            self.store.mark_sent(guild_id, message_id, user_id, choices)

    async def _refresh_and_reconcile(self, source: discord.TextChannel, message_id: int) -> None:
        lock = self._locks.setdefault(message_id, asyncio.Lock())
        async with lock:
            try:
                message = await source.fetch_message(message_id)
            except discord.NotFound:
                self.store.clear_message(self.config.guild_id, message_id)
                return
            await self._reconcile_locked(message)

    async def _channel(self, channel_id: int) -> discord.TextChannel:
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise WipeMonitorError(f"Channel {channel_id} is not a text channel")
        if channel.guild.id != self.config.guild_id:
            raise WipeMonitorError(f"Channel {channel_id} belongs to another guild")
        return channel

    async def reaction_changed(self, payload) -> None:
        if (
            payload.guild_id != self.config.guild_id
            or payload.channel_id != self.config.channel_id
            or str(payload.emoji) not in OPTIONS
        ):
            return
        source = await self._channel(self.config.channel_id)
        await self._refresh_and_reconcile(source, payload.message_id)

    async def reactions_cleared(self, payload) -> None:
        if (
            payload.guild_id != self.config.guild_id
            or payload.channel_id != self.config.channel_id
        ):
            return
        emoji = getattr(payload, "emoji", None)
        if emoji is not None and str(emoji) not in OPTIONS:
            return
        source = await self._channel(self.config.channel_id)
        await self._refresh_and_reconcile(source, payload.message_id)

    async def check_latest(self) -> tuple[discord.Message, dict[int, frozenset[str]]] | None:
        source = await self._channel(self.config.channel_id)
        message = await latest_eligible(source)
        if message is None:
            return None
        current = await overlaps_for_message(message, self.bot.user.id)
        if current is None:
            raise WipeMonitorError("Newest wipe message changed during the check")
        return message, current

    async def startup_check(self) -> None:
        result = await self.check_latest()
        if result is not None:
            source = await self._channel(self.config.channel_id)
            await self._refresh_and_reconcile(source, result[0].id)
