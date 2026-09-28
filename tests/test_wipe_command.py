from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from reporter.command_bot import CommandBot, wipe_check
from reporter.wipe_monitor import WipeMonitorError


@pytest.mark.asyncio
async def test_non_admin_cannot_run_wipe_check():
    interaction = SimpleNamespace(
        user=SimpleNamespace(guild_permissions=SimpleNamespace(administrator=False)),
        response=SimpleNamespace(send_message=AsyncMock()),
    )
    await wipe_check.callback(interaction)
    interaction.response.send_message.assert_awaited_once()
    assert interaction.response.send_message.await_args.kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_both_commands_register(monkeypatch):
    bot = CommandBot()
    monkeypatch.setattr(bot.tree, "sync", AsyncMock())
    await bot.setup_hook()
    assert bot.tree.get_command("report") is not None
    assert bot.tree.get_command("wipe-check") is not None


@pytest.mark.asyncio
async def test_raw_reaction_events_and_ready_use_monitor():
    bot = CommandBot()
    bot.wipe_monitor = SimpleNamespace(
        reaction_changed=AsyncMock(),
        reactions_cleared=AsyncMock(),
        startup_check=AsyncMock(),
    )
    payload = object()
    await bot.on_raw_reaction_add(payload)
    await bot.on_raw_reaction_remove(payload)
    await bot.on_raw_reaction_clear(payload)
    await bot.on_raw_reaction_clear_emoji(payload)
    await bot.on_ready()
    assert bot.wipe_monitor.reaction_changed.await_count == 2
    assert bot.wipe_monitor.reactions_cleared.await_count == 2
    bot.wipe_monitor.startup_check.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_history_returns_error_not_clean_result():
    monitor = SimpleNamespace(
        config=SimpleNamespace(guild_id=7),
        check_latest=AsyncMock(side_effect=WipeMonitorError("history denied")),
    )
    interaction = SimpleNamespace(
        user=SimpleNamespace(guild_permissions=SimpleNamespace(administrator=True)),
        guild_id=7,
        client=SimpleNamespace(wipe_monitor=monitor),
        response=SimpleNamespace(defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )
    await wipe_check.callback(interaction)
    assert "Could not finish" in interaction.followup.send.await_args.args[0]


@pytest.mark.asyncio
async def test_long_result_is_split_into_private_messages():
    message = SimpleNamespace(jump_url="https://discord.com/channels/7/6/8")
    overlaps = {user_id: frozenset({"✅", "⏰"}) for user_id in range(1000, 1300)}
    monitor = SimpleNamespace(
        config=SimpleNamespace(guild_id=7),
        check_latest=AsyncMock(return_value=(message, overlaps)),
    )
    interaction = SimpleNamespace(
        user=SimpleNamespace(guild_permissions=SimpleNamespace(administrator=True)),
        guild_id=7,
        client=SimpleNamespace(wipe_monitor=monitor),
        response=SimpleNamespace(defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )
    await wipe_check.callback(interaction)
    chunks = [call.args[0] for call in interaction.followup.send.await_args_list]
    assert interaction.response.defer.await_args.kwargs["ephemeral"] is True
    assert len(chunks) > 1
    assert all(len(chunk) < 2000 for chunk in chunks)
    assert all(call.kwargs["ephemeral"] is True for call in interaction.followup.send.await_args_list)
    assert all("<@" + str(user_id) + ">" in "".join(chunks) for user_id in overlaps)


@pytest.mark.asyncio
async def test_missing_monitor_reports_unavailable():
    interaction = SimpleNamespace(
        user=SimpleNamespace(guild_permissions=SimpleNamespace(administrator=True)),
        guild_id=7,
        client=SimpleNamespace(wipe_monitor=None),
        response=SimpleNamespace(defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )
    await wipe_check.callback(interaction)
    assert "unavailable" in interaction.followup.send.await_args.args[0]
