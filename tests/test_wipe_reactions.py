from types import SimpleNamespace

import pytest

from reporter.wipe_reactions import eligible, latest_eligible, overlaps_for_message


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
