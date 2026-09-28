import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from reporter.config import WipeConfig
from reporter.wipe_monitor import WipeMonitor
from reporter.wipe_state import AlertStore


def message():
    return SimpleNamespace(id=8, jump_url="https://discord.com/channels/7/6/8")


def bot():
    return SimpleNamespace(user=SimpleNamespace(id=99))


@pytest.mark.asyncio
async def test_same_overlap_alerts_once_across_events_and_store_reopen(
    tmp_path, monkeypatch
):
    admin = SimpleNamespace(send=AsyncMock())
    monkeypatch.setattr(
        "reporter.wipe_monitor.overlaps_for_message",
        AsyncMock(return_value={3: frozenset({"✅", "⏰"})}),
    )
    path = tmp_path / "state.sqlite3"
    first = WipeMonitor(bot(), WipeConfig(7, 6, 5), AlertStore(path))
    first._channel = AsyncMock(return_value=admin)
    await asyncio.gather(first.reconcile_message(message()), first.reconcile_message(message()))
    assert admin.send.await_count == 1
    assert admin.send.await_args.kwargs["allowed_mentions"].everyone is False
    first.store.close()

    second = WipeMonitor(bot(), WipeConfig(7, 6, 5), AlertStore(path))
    second._channel = AsyncMock(return_value=admin)
    await second.reconcile_message(message())
    assert admin.send.await_count == 1
    second.store.close()


@pytest.mark.asyncio
async def test_removed_then_restored_overlap_alerts_again(tmp_path, monkeypatch):
    admin = SimpleNamespace(send=AsyncMock())
    duplicate = {3: frozenset({"✅", "⏰"})}
    monkeypatch.setattr(
        "reporter.wipe_monitor.overlaps_for_message",
        AsyncMock(side_effect=[duplicate, {}, duplicate]),
    )
    store = AlertStore(tmp_path / "state.sqlite3")
    monitor = WipeMonitor(bot(), WipeConfig(7, 6, 5), store)
    monitor._channel = AsyncMock(return_value=admin)
    await monitor.reconcile_message(message())
    await monitor.reconcile_message(message())
    await monitor.reconcile_message(message())
    assert admin.send.await_count == 2
    store.close()


@pytest.mark.asyncio
async def test_failed_send_does_not_record_alert(tmp_path, monkeypatch):
    admin = SimpleNamespace(send=AsyncMock(side_effect=PermissionError("send denied")))
    monkeypatch.setattr(
        "reporter.wipe_monitor.overlaps_for_message",
        AsyncMock(return_value={3: frozenset({"✅", "⏰"})}),
    )
    store = AlertStore(tmp_path / "state.sqlite3")
    monitor = WipeMonitor(bot(), WipeConfig(7, 6, 5), store)
    monitor._channel = AsyncMock(return_value=admin)
    with pytest.raises(PermissionError, match="send denied"):
        await monitor.reconcile_message(message())
    assert store.active_users(7, 8) == set()
    store.close()


@pytest.mark.asyncio
async def test_third_option_event_checks_its_message_even_when_old(tmp_path, monkeypatch):
    source = SimpleNamespace(fetch_message=AsyncMock(return_value=message()))
    admin = SimpleNamespace(send=AsyncMock())
    monkeypatch.setattr(
        "reporter.wipe_monitor.overlaps_for_message",
        AsyncMock(return_value={3: frozenset({"✅", "⏰"})}),
    )
    store = AlertStore(tmp_path / "state.sqlite3")
    monitor = WipeMonitor(bot(), WipeConfig(7, 6, 5), store)
    monitor._channel = AsyncMock(side_effect=lambda channel_id: source if channel_id == 6 else admin)
    payload = SimpleNamespace(guild_id=7, channel_id=6, message_id=8, emoji="❌")
    await monitor.reaction_changed(payload)
    source.fetch_message.assert_awaited_once_with(8)
    admin.send.assert_awaited_once()
    store.close()


@pytest.mark.asyncio
async def test_startup_checks_latest_message(tmp_path, monkeypatch):
    source = SimpleNamespace()
    admin = SimpleNamespace(send=AsyncMock())
    monkeypatch.setattr("reporter.wipe_monitor.latest_eligible", AsyncMock(return_value=message()))
    monkeypatch.setattr(
        "reporter.wipe_monitor.overlaps_for_message",
        AsyncMock(return_value={3: frozenset({"✅", "⏰"})}),
    )
    store = AlertStore(tmp_path / "state.sqlite3")
    monitor = WipeMonitor(bot(), WipeConfig(7, 6, 5), store)
    monitor._channel = AsyncMock(side_effect=lambda channel_id: source if channel_id == 6 else admin)
    await monitor.startup_check()
    admin.send.assert_awaited_once()
    store.close()
