# Wipe Reaction Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Detect users with two or more of ✅, ⏰, and ❌ on wipe messages, alert a separate admin channel, and provide an administrator-only command to check the newest eligible message.

**Architecture:** Add a focused reaction reader and monitor to the existing discord.py client. The monitor reconciles current Discord reactions on raw events and startup, while SQLite records active alerts across restarts. The existing reporting client and process remain in place.

**Tech Stack:** Python 3.13 in the deployed Debian LXC; discord.py 2.7.1; standard-library sqlite3; pytest and pytest-asyncio.

**Spec:** docs/wipe-reaction-monitor-design.md

## Global Constraints

- Watch exactly one configured guild and wipe channel; send automatic alerts to one configured admin channel.
- A message is eligible only while all three reaction emojis ✅, ⏰, and ❌ are present.
- Count distinct emoji choices by user ID; ordinary and burst reactions on one emoji count as one choice.
- The on-demand and startup searches inspect at most 1,000 messages, newest first.
- On-demand results are private and available only to server administrators.
- Persist sent-alert state using systemd StateDirectory=reportingbot; do not add a second process or container.
- A wipe-monitor failure must not stop the existing reporting feature.
- No live /report command is part of verification. Restarting the service drops its in-memory report queue.
- The local Windows venv launcher is stale. For local tests, set PYTHONPATH to venv/Lib/site-packages and run the bundled Python under the current user's .cache/codex-runtimes/codex-primary-runtime/dependencies/python directory. The baseline suite had 42 passing tests on 2026-09-28.
- The deployed checkout is on an older, divergent master commit. The rollout must preserve its current commit and ignored .env instead of assuming a fast-forward update.

## Review Focus

Each condition below gets an explicit test in the owning task.

1. A person uses both normal and burst reactions for one emoji: count one choice (Task 2).
2. A reactor has left the guild: retain their user ID in overlap results (Task 2).
3. Two raw events for one message arrive together: send one alert per newly overlapping user (Task 4).
4. Discord denies reaction-user or history access: return an error, never a false “no overlaps” result (Tasks 2 and 5).
5. A restart finds an already alerted overlap: do not alert again; a removed and later restored overlap does alert again (Tasks 3 and 4).

## File Map

- reporter/config.py: optional wipe settings and state path, separate from required reporting settings.
- reporter/wipe_reactions.py: eligibility, reaction-user collection, and newest-message search.
- reporter/wipe_state.py: SQLite active-alert records.
- reporter/wipe_monitor.py: reaction-event reconciliation, startup scan, alert delivery, and Discord access.
- reporter/command_bot.py: raw reaction handlers and administrator-only /wipe-check.
- main.py: load optional wipe settings without stopping reporting on wipe-only errors.
- deploy/reportingbot.service: managed writable state directory.
- .gitignore, .env.example, README.md, SETUP.md: local state and operator instructions.
- tests/test_wipe_config.py, tests/test_wipe_reactions.py, tests/test_wipe_state.py, tests/test_wipe_monitor.py, tests/test_wipe_command.py: focused offline coverage.

---

### Task 1: Optional Wipe Configuration

**Files:**
- Modify: reporter/config.py
- Test: tests/test_wipe_config.py

**Interfaces:**
- Produces WipeConfig(guild_id: int, channel_id: int, admin_channel_id: int).
- Produces load_wipe_config() -> WipeConfig | None and wipe_state_path() -> pathlib.Path.
- Existing validate_config() keeps its current reporting-only contract.

- [ ] **Step 1: Write failing configuration tests.**

~~~python
from pathlib import Path
import pytest
from reporter.config import ConfigError, load_wipe_config, wipe_state_path

KEYS = ("WIPE_GUILD_ID", "WIPE_CHANNEL_ID", "WIPE_ADMIN_CHANNEL_ID")

def test_wipe_config_disabled_when_all_ids_are_blank(monkeypatch):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    assert load_wipe_config() is None

def test_partial_wipe_config_names_invalid_keys(monkeypatch):
    monkeypatch.setenv("WIPE_GUILD_ID", "7")
    monkeypatch.setenv("WIPE_CHANNEL_ID", "0")
    monkeypatch.delenv("WIPE_ADMIN_CHANNEL_ID", raising=False)
    with pytest.raises(ConfigError, match="WIPE_CHANNEL_ID.*WIPE_ADMIN_CHANNEL_ID"):
        load_wipe_config()

def test_wipe_state_path_prefers_systemd_directory(monkeypatch):
    monkeypatch.delenv("WIPE_STATE_PATH", raising=False)
    monkeypatch.setenv("STATE_DIRECTORY", "/var/lib/reportingbot")
    assert wipe_state_path() == Path("/var/lib/reportingbot/wipe_alerts.sqlite3")

def test_valid_wipe_config_parses_three_ids(monkeypatch):
    monkeypatch.setenv("WIPE_GUILD_ID", "7")
    monkeypatch.setenv("WIPE_CHANNEL_ID", "8")
    monkeypatch.setenv("WIPE_ADMIN_CHANNEL_ID", "9")
    settings = load_wipe_config()
    assert (settings.guild_id, settings.channel_id, settings.admin_channel_id) == (7, 8, 9)

def test_explicit_state_path_overrides_systemd(monkeypatch, tmp_path):
    target = tmp_path / "alerts.sqlite3"
    monkeypatch.setenv("STATE_DIRECTORY", "/var/lib/reportingbot")
    monkeypatch.setenv("WIPE_STATE_PATH", str(target))
    assert wipe_state_path() == target
~~~

- [ ] **Step 2: Run the new file and confirm import failures.**

~~~powershell
$env:PYTHONPATH = (Resolve-Path 'venv\Lib\site-packages').Path
& (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe') -m pytest tests/test_wipe_config.py -q
~~~

Expected: tests fail because the wipe configuration interfaces do not exist.

- [ ] **Step 3: Add the settings and parser.**

~~~python
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class WipeConfig:
    guild_id: int
    channel_id: int
    admin_channel_id: int

def load_wipe_config() -> WipeConfig | None:
    names = ("WIPE_GUILD_ID", "WIPE_CHANNEL_ID", "WIPE_ADMIN_CHANNEL_ID")
    raw = {name: os.getenv(name, "").strip() for name in names}
    if not any(raw.values()):
        return None
    invalid = [name for name, value in raw.items()
               if not value.isdecimal() or int(value) <= 0]
    if invalid:
        raise ConfigError("Missing or invalid wipe configuration: " + ", ".join(invalid))
    return WipeConfig(*(int(raw[name]) for name in names))

def wipe_state_path() -> Path:
    override = os.getenv("WIPE_STATE_PATH", "").strip()
    if override:
        return Path(override)
    directory = os.getenv("STATE_DIRECTORY", "").strip()
    return Path(directory or "data") / "wipe_alerts.sqlite3"
~~~

Keep validate_config() unchanged.

- [ ] **Step 4: Run the configuration tests and existing config tests, then commit.**

~~~powershell
$env:PYTHONPATH = (Resolve-Path 'venv\Lib\site-packages').Path
& (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe') -m pytest tests/test_wipe_config.py tests/test_config.py -q
git add reporter/config.py tests/test_wipe_config.py
git commit -m "Add optional wipe monitor configuration"
~~~

Expected: all selected tests pass.

### Task 2: Reaction Snapshot and Newest Eligible Message

**Files:**
- Create: reporter/wipe_reactions.py
- Test: tests/test_wipe_reactions.py

**Interfaces:**
- Produces OPTIONS: tuple[str, str, str] and HISTORY_LIMIT = 1000.
- Produces eligible(message: discord.Message) -> bool.
- Produces overlaps_for_message(message: discord.Message, bot_user_id: int) -> dict[int, frozenset[str]] | None. None means ineligible; exceptions mean incomplete data.
- Produces latest_eligible(channel: discord.TextChannel, limit: int = HISTORY_LIMIT) -> discord.Message | None.

- [ ] **Step 1: Write tests with fake message, reaction, and history iterators.**

~~~python
import pytest
from types import SimpleNamespace
from reporter.wipe_reactions import eligible, overlaps_for_message, latest_eligible

class FakeReaction:
    def __init__(self, emoji, normal=(), burst=()):
        self.emoji = emoji
        self.people = {"normal": normal, "burst": burst}
    async def users(self, *, type):
        for user_id in self.people[type.name]:
            yield SimpleNamespace(id=user_id)

@pytest.mark.asyncio
async def test_two_distinct_choices_overlap_and_one_emoji_twice_does_not():
    message = SimpleNamespace(reactions=[
        FakeReaction("✅", normal=(10, 20), burst=(10,)),
        FakeReaction("⏰", normal=(20,)),
        FakeReaction("❌", normal=(30,)),
    ])
    assert await overlaps_for_message(message, bot_user_id=999) == {
        20: frozenset({"✅", "⏰"})
    }

@pytest.mark.asyncio
async def test_latest_eligible_stops_at_newest_match():
    older = SimpleNamespace(reactions=[FakeReaction("✅"), FakeReaction("⏰"), FakeReaction("❌")])
    newer = SimpleNamespace(reactions=[FakeReaction("✅")])
    class Channel:
        async def history(self, *, limit):
            assert limit == 1000
            yield newer
            yield older
    assert await latest_eligible(Channel()) is older

@pytest.mark.asyncio
async def test_three_choices_ignore_bot_and_unrelated_emoji():
    message = SimpleNamespace(reactions=[
        FakeReaction("✅", normal=(20, 999)),
        FakeReaction("⏰", normal=(20, 999)),
        FakeReaction("❌", normal=(20, 999)),
        FakeReaction("🔥", normal=(30,)),
    ])
    assert await overlaps_for_message(message, bot_user_id=999) == {
        20: frozenset({"✅", "⏰", "❌"})
    }

@pytest.mark.asyncio
async def test_missing_third_option_is_ineligible():
    message = SimpleNamespace(reactions=[
        FakeReaction("✅", normal=(20,)), FakeReaction("⏰", normal=(20,))
    ])
    assert eligible(message) is False
    assert await overlaps_for_message(message, bot_user_id=999) is None

@pytest.mark.asyncio
async def test_failed_reactor_fetch_is_not_an_empty_result():
    class BrokenReaction(FakeReaction):
        async def users(self, *, type):
            raise PermissionError("reaction users unavailable")
            yield
    message = SimpleNamespace(reactions=[
        BrokenReaction("✅"), FakeReaction("⏰"), FakeReaction("❌")
    ])
    with pytest.raises(PermissionError, match="unavailable"):
        await overlaps_for_message(message, bot_user_id=999)
~~~

The fake users contain only IDs, so the tests also cover a member who left the guild. The history fake asserts the 1,000-message limit passed to Discord.

- [ ] **Step 2: Run the reaction tests and confirm module import failure.**

~~~powershell
$env:PYTHONPATH = (Resolve-Path 'venv\Lib\site-packages').Path
& (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe') -m pytest tests/test_wipe_reactions.py -q
~~~

- [ ] **Step 3: Implement the small reaction reader.**

~~~python
from collections import defaultdict
import discord

OPTIONS = ("✅", "⏰", "❌")
HISTORY_LIMIT = 1000

def eligible(message: discord.Message) -> bool:
    present = {str(reaction.emoji) for reaction in message.reactions}
    return all(emoji in present for emoji in OPTIONS)

async def overlaps_for_message(
    message: discord.Message, bot_user_id: int
) -> dict[int, frozenset[str]] | None:
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
    return {user_id: frozenset(emojis) for user_id, emojis in selected.items()
            if len(emojis) >= 2}

async def latest_eligible(
    channel: discord.TextChannel, limit: int = HISTORY_LIMIT
) -> discord.Message | None:
    async for message in channel.history(limit=limit):
        if eligible(message):
            return message
    return None
~~~

Do not catch reaction-user or history exceptions here; callers must distinguish errors from an empty result.

- [ ] **Step 4: Run focused and full offline tests, then commit.**

~~~powershell
$env:PYTHONPATH = (Resolve-Path 'venv\Lib\site-packages').Path
& (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe') -m pytest tests/test_wipe_reactions.py -q
$env:PYTHONPATH = (Resolve-Path 'venv\Lib\site-packages').Path
& (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe') -m pytest -q
git add reporter/wipe_reactions.py tests/test_wipe_reactions.py
git commit -m "Read wipe reaction overlaps"
~~~

### Task 3: Durable Alert State

**Files:**
- Create: reporter/wipe_state.py
- Modify: .gitignore
- Modify: deploy/reportingbot.service
- Test: tests/test_wipe_state.py

**Interfaces:**
- Produces AlertStore(path: pathlib.Path).
- Methods: active_users(guild_id: int, message_id: int) -> set[int]; mark_sent(guild_id: int, message_id: int, user_id: int, choices: frozenset[str]) -> None; clear_except(guild_id: int, message_id: int, current_ids: set[int]) -> None; clear_message(guild_id: int, message_id: int) -> None; close() -> None.
- Only mark_sent follows a successful Discord send.

- [ ] **Step 1: Write persistence and resolution tests.**

~~~python
from reporter.wipe_state import AlertStore

def test_sent_alert_survives_reopen_and_can_be_cleared(tmp_path):
    path = tmp_path / "alerts.sqlite3"
    store = AlertStore(path)
    store.mark_sent(1, 2, 3, frozenset({"✅", "⏰"}))
    store.close()
    reopened = AlertStore(path)
    assert reopened.active_users(1, 2) == {3}
    reopened.clear_except(1, 2, set())
    assert reopened.active_users(1, 2) == set()
    reopened.close()

def test_keys_are_per_guild_message_and_user(tmp_path):
    store = AlertStore(tmp_path / "alerts.sqlite3")
    store.mark_sent(1, 2, 3, frozenset({"✅", "⏰"}))
    store.mark_sent(1, 2, 3, frozenset({"✅", "⏰"}))
    store.mark_sent(1, 4, 3, frozenset({"✅", "❌"}))
    store.mark_sent(5, 2, 3, frozenset({"⏰", "❌"}))
    assert store.active_users(1, 2) == {3}
    store.clear_message(1, 2)
    assert store.active_users(1, 2) == set()
    assert store.active_users(1, 4) == {3}
    assert store.active_users(5, 2) == {3}
    store.close()
~~~

The second test proves idempotency and separation across messages and guilds.

- [ ] **Step 2: Run the state tests and confirm import failure.**

~~~powershell
$env:PYTHONPATH = (Resolve-Path 'venv\Lib\site-packages').Path
& (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe') -m pytest tests/test_wipe_state.py -q
~~~

- [ ] **Step 3: Add SQLite storage and the managed directory.**

~~~python
import json
import sqlite3
from pathlib import Path

class AlertStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS active_alerts ("
            "guild_id INTEGER NOT NULL, message_id INTEGER NOT NULL, "
            "user_id INTEGER NOT NULL, choices TEXT NOT NULL, alerted_at TEXT NOT NULL, "
            "PRIMARY KEY (guild_id, message_id, user_id))"
        )
        self.connection.commit()

    def active_users(self, guild_id: int, message_id: int) -> set[int]:
        rows = self.connection.execute(
            "SELECT user_id FROM active_alerts WHERE guild_id=? AND message_id=?",
            (guild_id, message_id),
        )
        return {row[0] for row in rows}

    def mark_sent(self, guild_id: int, message_id: int, user_id: int,
                  choices: frozenset[str]) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO active_alerts VALUES (?, ?, ?, ?, datetime('now'))",
                (guild_id, message_id, user_id, json.dumps(sorted(choices))),
            )

    def clear_except(self, guild_id: int, message_id: int,
                     current_ids: set[int]) -> None:
        stale = self.active_users(guild_id, message_id) - current_ids
        with self.connection:
            self.connection.executemany(
                "DELETE FROM active_alerts WHERE guild_id=? AND message_id=? AND user_id=?",
                ((guild_id, message_id, user_id) for user_id in stale),
            )

    def clear_message(self, guild_id: int, message_id: int) -> None:
        with self.connection:
            self.connection.execute(
                "DELETE FROM active_alerts WHERE guild_id=? AND message_id=?",
                (guild_id, message_id),
            )

    def close(self) -> None:
        self.connection.close()
~~~

Add data/ to .gitignore and StateDirectory=reportingbot plus StateDirectoryMode=0700 under [Service] in deploy/reportingbot.service.

- [ ] **Step 4: Run state tests and validate the service file before committing.**

~~~powershell
$env:PYTHONPATH = (Resolve-Path 'venv\Lib\site-packages').Path
& (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe') -m pytest tests/test_wipe_state.py -q
git diff --check
git add reporter/wipe_state.py tests/test_wipe_state.py .gitignore deploy/reportingbot.service
git commit -m "Persist wipe alerts in managed service state"
~~~

### Task 4: Event Monitor and Startup Reconciliation

**Files:**
- Create: reporter/wipe_monitor.py
- Test: tests/test_wipe_monitor.py

**Interfaces:**
- Consumes WipeConfig, AlertStore, latest_eligible, and overlaps_for_message.
- Produces WipeMonitor(bot: discord.Client, config: WipeConfig, store: AlertStore).
- Produces WipeMonitorError(Exception) for an inaccessible or mismatched channel.
- Methods: reaction_changed(payload) -> None; reactions_cleared(payload) -> None; startup_check() -> None; check_latest() -> tuple[discord.Message, dict[int, frozenset[str]]] | None.
- The monitor raises Discord/storage errors to its caller; bot event handlers log them and keep reporting online.

- [ ] **Step 1: Write tests for one alert, duplicate events, removal, and restart.**

~~~python
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from reporter.wipe_monitor import WipeMonitor
from reporter.wipe_state import AlertStore
from reporter.config import WipeConfig

@pytest.mark.asyncio
async def test_same_overlap_alerts_once_across_events_and_store_reopen(
    tmp_path, monkeypatch
):
    message = SimpleNamespace(id=8, guild=SimpleNamespace(id=7),
                              jump_url="https://discord.com/channels/7/6/8")
    admin = SimpleNamespace(send=AsyncMock())
    bot = SimpleNamespace(user=SimpleNamespace(id=99))
    monkeypatch.setattr("reporter.wipe_monitor.overlaps_for_message",
                        AsyncMock(return_value={3: frozenset({"✅", "⏰"})}))
    path = tmp_path / "state.sqlite3"
    first = WipeMonitor(bot, WipeConfig(7, 6, 5), AlertStore(path))
    first._channel = AsyncMock(return_value=admin)
    await asyncio.gather(first.reconcile_message(message),
                         first.reconcile_message(message))
    assert admin.send.await_count == 1
    first.store.close()
    second = WipeMonitor(bot, WipeConfig(7, 6, 5), AlertStore(path))
    second._channel = AsyncMock(return_value=admin)
    await second.reconcile_message(message)
    assert admin.send.await_count == 1
    second.store.close()

@pytest.mark.asyncio
async def test_removed_then_restored_overlap_alerts_again(tmp_path, monkeypatch):
    message = SimpleNamespace(id=8, jump_url="https://discord.com/channels/7/6/8")
    admin = SimpleNamespace(send=AsyncMock())
    bot = SimpleNamespace(user=SimpleNamespace(id=99))
    duplicate = {3: frozenset({"✅", "⏰"})}
    monkeypatch.setattr("reporter.wipe_monitor.overlaps_for_message",
                        AsyncMock(side_effect=[duplicate, {}, duplicate]))
    store = AlertStore(tmp_path / "state.sqlite3")
    monitor = WipeMonitor(bot, WipeConfig(7, 6, 5), store)
    monitor._channel = AsyncMock(return_value=admin)
    await monitor.reconcile_message(message)
    await monitor.reconcile_message(message)
    await monitor.reconcile_message(message)
    assert admin.send.await_count == 2
    store.close()

@pytest.mark.asyncio
async def test_failed_send_does_not_record_alert(tmp_path, monkeypatch):
    message = SimpleNamespace(id=8, jump_url="https://discord.com/channels/7/6/8")
    admin = SimpleNamespace(send=AsyncMock(side_effect=PermissionError("send denied")))
    bot = SimpleNamespace(user=SimpleNamespace(id=99))
    monkeypatch.setattr("reporter.wipe_monitor.overlaps_for_message",
                        AsyncMock(return_value={3: frozenset({"✅", "⏰"})}))
    store = AlertStore(tmp_path / "state.sqlite3")
    monitor = WipeMonitor(bot, WipeConfig(7, 6, 5), store)
    monitor._channel = AsyncMock(return_value=admin)
    with pytest.raises(PermissionError, match="send denied"):
        await monitor.reconcile_message(message)
    assert store.active_users(7, 8) == set()
    store.close()

@pytest.mark.asyncio
async def test_third_option_event_checks_its_message_even_when_old(tmp_path, monkeypatch):
    message = SimpleNamespace(id=8, jump_url="https://discord.com/channels/7/6/8")
    source = SimpleNamespace(fetch_message=AsyncMock(return_value=message))
    admin = SimpleNamespace(send=AsyncMock())
    bot = SimpleNamespace(user=SimpleNamespace(id=99))
    monkeypatch.setattr("reporter.wipe_monitor.overlaps_for_message",
                        AsyncMock(return_value={3: frozenset({"✅", "⏰"})}))
    store = AlertStore(tmp_path / "state.sqlite3")
    monitor = WipeMonitor(bot, WipeConfig(7, 6, 5), store)
    monitor._channel = AsyncMock(side_effect=lambda channel_id:
                                 source if channel_id == 6 else admin)
    payload = SimpleNamespace(guild_id=7, channel_id=6, message_id=8, emoji="❌")
    await monitor.reaction_changed(payload)
    source.fetch_message.assert_awaited_once_with(8)
    admin.send.assert_awaited_once()
    store.close()
~~~

The raw-event test proves the handler uses the payload message ID and checks overlaps that existed before the third option appeared.

- [ ] **Step 2: Run the new monitor tests and confirm import failure.**

~~~powershell
$env:PYTHONPATH = (Resolve-Path 'venv\Lib\site-packages').Path
& (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe') -m pytest tests/test_wipe_monitor.py -q
~~~

- [ ] **Step 3: Implement message reconciliation with a per-message lock.**

~~~python
import asyncio
import discord
from reporter.wipe_reactions import OPTIONS, latest_eligible, overlaps_for_message

class WipeMonitorError(Exception):
    pass

class WipeMonitor:
    def __init__(self, bot, config, store):
        self.bot, self.config, self.store = bot, config, store
        self._locks: dict[int, asyncio.Lock] = {}

    async def reconcile_message(self, message):
        lock = self._locks.setdefault(message.id, asyncio.Lock())
        async with lock:
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
                text = (f"<@{user_id}> selected {' '.join(sorted(choices))} "
                        f"on {message.jump_url}")
                await admin.send(text, allowed_mentions=discord.AllowedMentions.none())
                self.store.mark_sent(guild_id, message_id, user_id, choices)
~~~

Add these methods inside WipeMonitor. The source and admin channels must both be text channels in the configured guild. A missing channel or wrong guild raises WipeMonitorError; Discord permission errors propagate to the bot handler.

~~~python
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
        if (payload.guild_id != self.config.guild_id
                or payload.channel_id != self.config.channel_id
                or str(payload.emoji) not in OPTIONS):
            return
        source = await self._channel(self.config.channel_id)
        try:
            message = await source.fetch_message(payload.message_id)
        except discord.NotFound:
            self.store.clear_message(self.config.guild_id, payload.message_id)
            return
        await self.reconcile_message(message)

    async def reactions_cleared(self, payload) -> None:
        if (payload.guild_id != self.config.guild_id
                or payload.channel_id != self.config.channel_id):
            return
        emoji = getattr(payload, "emoji", None)
        if emoji is not None and str(emoji) not in OPTIONS:
            return
        source = await self._channel(self.config.channel_id)
        try:
            message = await source.fetch_message(payload.message_id)
        except discord.NotFound:
            self.store.clear_message(self.config.guild_id, payload.message_id)
            return
        await self.reconcile_message(message)

    async def check_latest(self):
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
            await self.reconcile_message(result[0])
~~~

- [ ] **Step 4: Run event tests, full suite, and commit.**

~~~powershell
$env:PYTHONPATH = (Resolve-Path 'venv\Lib\site-packages').Path
& (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe') -m pytest tests/test_wipe_monitor.py -q
$env:PYTHONPATH = (Resolve-Path 'venv\Lib\site-packages').Path
& (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe') -m pytest -q
git add reporter/wipe_monitor.py tests/test_wipe_monitor.py
git commit -m "Monitor wipe reaction changes and startup state"
~~~

### Task 5: Bot Wiring, Private Command, and Setup Instructions

**Files:**
- Modify: reporter/command_bot.py
- Modify: main.py
- Modify: .env.example
- Modify: README.md
- Modify: SETUP.md
- Test: tests/test_wipe_command.py
- Test: tests/test_wipe_config.py

**Interfaces:**
- CommandBot accepts wipe_config: WipeConfig | None = None and state_path: Path | None = None.
- CommandBot.wipe_monitor is WipeMonitor | None.
- /wipe-check calls WipeMonitor.check_latest() and does not change sent-alert state.

- [ ] **Step 1: Write tests for command access and bot registration.**

~~~python
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from reporter.command_bot import CommandBot, wipe_check

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
async def test_failed_history_returns_error_not_clean_result():
    from reporter.wipe_monitor import WipeMonitorError
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
    overlaps = {user_id: frozenset({"✅", "⏰"})
                for user_id in range(1000, 1100)}
    monitor = SimpleNamespace(config=SimpleNamespace(guild_id=7),
                              check_latest=AsyncMock(return_value=(message, overlaps)))
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
    assert all(call.kwargs["ephemeral"] is True
               for call in interaction.followup.send.await_args_list)
    assert all("<@" + str(user_id) + ">" in "".join(chunks)
               for user_id in overlaps)

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
~~~

The missing-monitor test exercises a disabled wipe feature while the reporting bot remains constructed. The long-result test proves private followups remain under Discord's message limit.

- [ ] **Step 2: Run the command tests and confirm failure.**

~~~powershell
$env:PYTHONPATH = (Resolve-Path 'venv\Lib\site-packages').Path
& (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe') -m pytest tests/test_wipe_command.py -q
~~~

- [ ] **Step 3: Wire the monitor and slash command.**

~~~python
# In CommandBot.__init__, after CommandTree construction:
self.wipe_monitor = None
if wipe_config is not None:
    try:
        store = AlertStore(state_path or wipe_state_path())
        self.wipe_monitor = WipeMonitor(self, wipe_config, store)
    except (OSError, sqlite3.Error):
        log.exception("Wipe monitor state could not be opened")

# In setup_hook:
self.tree.add_command(report)
self.tree.add_command(wipe_check)

# Add guarded delegation methods to CommandBot:
async def _wipe_event(self, payload, *, cleared: bool = False):
    if self.wipe_monitor is not None:
        try:
            if cleared:
                await self.wipe_monitor.reactions_cleared(payload)
            else:
                await self.wipe_monitor.reaction_changed(payload)
        except (discord.HTTPException, OSError, sqlite3.Error, WipeMonitorError):
            log.exception("Wipe reaction check failed")

async def on_raw_reaction_add(self, payload):
    await self._wipe_event(payload)

async def on_raw_reaction_remove(self, payload):
    await self._wipe_event(payload)

async def on_raw_reaction_clear(self, payload):
    await self._wipe_event(payload, cleared=True)

async def on_raw_reaction_clear_emoji(self, payload):
    await self._wipe_event(payload, cleared=True)

async def on_ready(self):
    log.info("Command bot online as %s", self.user)
    if self.wipe_monitor is not None:
        try:
            await self.wipe_monitor.startup_check()
        except (discord.HTTPException, OSError, sqlite3.Error, WipeMonitorError):
            log.exception("Startup wipe check failed")
~~~

Set intents.reactions = True explicitly in CommandBot.__init__.

~~~python
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
        await interaction.followup.send("No wipe message with all three reactions was found.",
                                        ephemeral=True)
        return
    message, overlaps = result
    lines = [f"<@{user_id}>: {' '.join(sorted(choices))}"
             for user_id, choices in sorted(overlaps.items())]
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
~~~

In main.py, load wipe settings after the existing reporting validation and before constructing the bot:

~~~python
try:
    wipe_config = load_wipe_config()
except ConfigError as exc:
    log.error("Wipe monitor disabled: %s", exc)
    wipe_config = None
bot = CommandBot(wipe_config=wipe_config, state_path=wipe_state_path())
~~~

Add the three channel IDs and optional state path to .env.example; explain permissions, administrator command, and same-container service update in README.md and SETUP.md.

- [ ] **Step 4: Run focused and full tests, check the diff, and commit.**

~~~powershell
$env:PYTHONPATH = (Resolve-Path 'venv\Lib\site-packages').Path
& (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe') -m pytest tests/test_wipe_command.py tests/test_wipe_config.py -q
$env:PYTHONPATH = (Resolve-Path 'venv\Lib\site-packages').Path
& (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe') -m pytest -q
git diff --check
git add reporter/command_bot.py main.py .env.example README.md SETUP.md tests/test_wipe_command.py tests/test_wipe_config.py
git commit -m "Expose wipe checks through existing Discord bot"
~~~

### Task 6: Container Rollout and Live Verification

**Files:**
- No product source changes. Update only operator notes if the observed deployment differs from this plan.

**Interfaces:**
- Consumes the reviewed and integrated code from Tasks 1–5.
- Produces a running service in the existing container and observed alert/command results.

- [ ] **Step 1: Complete local gates before touching the running service.**

~~~powershell
$env:PYTHONPATH = (Resolve-Path 'venv\Lib\site-packages').Path
& (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe') -m pytest -q
git diff --check
git status --short
~~~

Expected: all tests pass, no whitespace errors, and no unexpected changes. Review the branch and integrate it before deployment.

- [ ] **Step 2: Preflight the existing container without displaying .env contents.**

Run inside the bot container after entering it through the existing SSH access:

~~~bash
hostname
git -C /opt/reportingbot status --short
git -C /opt/reportingbot rev-parse --short HEAD
test -f /opt/reportingbot/.env
systemctl is-active reportingbot
~~~

Expected: correct container, clean checkout, configuration file present, service active. Record the current commit. The deployed master was observed to diverge from the public master; do not use git pull as if a fast-forward were guaranteed. Schedule restart when the in-memory report queue can be discarded.

- [ ] **Step 3: Preserve the current deployment and install the integrated code.**

Take a snapshot of the existing Proxmox bot container through the operator's normal snapshot workflow. Then, inside the container, preserve the current checkout commit and fetch the reviewed branch after it has been integrated into origin/master:

~~~bash
git -C /opt/reportingbot branch backup-before-wipe-reactions HEAD
git -C /opt/reportingbot fetch origin
git -C /opt/reportingbot rev-parse --short origin/master
~~~

Confirm that the fetched commit contains the reviewed wipe feature. Stop the service, switch the clean checkout to the fetched commit, keep the ignored .env file, install the updated unit, and reload systemd:

~~~bash
systemctl stop reportingbot
git -C /opt/reportingbot switch --detach origin/master
cp -p /etc/systemd/system/reportingbot.service /etc/systemd/system/reportingbot.service.pre-wipe
install -o root -g root -m 0644 /opt/reportingbot/deploy/reportingbot.service /etc/systemd/system/reportingbot.service
systemctl daemon-reload
~~~

Edit /opt/reportingbot/.env in place to add the three channel IDs; do not print or paste token values. Check the file is owned by the service account and mode 0600. Run the full suite with /opt/reportingbot/.venv/bin/python -m pytest -q before starting the service.

- [ ] **Step 4: Start, observe, and test only the wipe feature.**

~~~bash
systemctl start reportingbot
systemctl is-active reportingbot
systemctl show reportingbot -p StateDirectory
journalctl -u reportingbot -n 80 --no-pager
~~~

Expected: active service, StateDirectory=reportingbot, both existing Discord clients online, wipe monitor configured, and no startup error. Create a harmless wipe message with the three emojis in the configured channel. Have a test user choose two options; confirm one admin-channel alert with the correct message link. Run /wipe-check as an administrator and confirm a private current result. Remove one reaction, add it again, and confirm a new alert. Restart at a quiet time and confirm an unchanged overlap does not alert again. Confirm /report is registered without invoking it.

- [ ] **Step 5: Roll back if the live checks fail.**

Stop the service, switch the checkout to backup-before-wipe-reactions, restore the prior systemd unit from its saved copy, reload systemd, and restart. Extra WIPE_* entries in .env can remain ignored by the old code. Keep the SQLite database for diagnosis; do not delete it as part of rollback.

~~~bash
systemctl stop reportingbot
git -C /opt/reportingbot switch --detach backup-before-wipe-reactions
cp -p /etc/systemd/system/reportingbot.service.pre-wipe /etc/systemd/system/reportingbot.service
systemctl daemon-reload
systemctl start reportingbot
systemctl is-active reportingbot
~~~

Check journalctl for the original bot's healthy startup.

## Technical References

- discord.py API reference: https://discordpy.readthedocs.io/en/stable/api.html — raw reaction events, reaction-user iteration, and channel history.
- systemd service execution reference: https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml — StateDirectory with ProtectSystem.
