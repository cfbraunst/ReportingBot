"""Read wipe attendance reactions from current Discord message data."""

from collections import defaultdict

import discord

OPTIONS = ("✅", "⏰", "❌")
HISTORY_LIMIT = 1000


def eligible(message: discord.Message) -> bool:
    """A wipe message has all three attendance reactions available."""
    present = {str(reaction.emoji) for reaction in message.reactions}
    return all(emoji in present for emoji in OPTIONS)


async def overlaps_for_message(
    message: discord.Message, bot_user_id: int
) -> dict[int, frozenset[str]] | None:
    """Return users with multiple choices, or None for an ineligible message."""
    if not eligible(message):
        return None

    selected: dict[int, set[str]] = defaultdict(set)
    for reaction in message.reactions:
        emoji = str(reaction.emoji)
        if emoji not in OPTIONS:
            continue
        for reaction_type in (discord.ReactionType.normal, discord.ReactionType.burst):
            async for user in reaction.users(type=reaction_type):
                if user.id != bot_user_id:
                    selected[user.id].add(emoji)

    return {
        user_id: frozenset(emojis)
        for user_id, emojis in selected.items()
        if len(emojis) >= 2
    }


async def latest_eligible(
    channel: discord.TextChannel, limit: int = HISTORY_LIMIT
) -> discord.Message | None:
    """Find the newest qualifying message within bounded channel history."""
    async for message in channel.history(limit=limit):
        if eligible(message):
            return message
    return None
