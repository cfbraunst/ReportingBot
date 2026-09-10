import asyncio

import pytest

from reporter import command_bot, jobs
from reporter.jobs import ReportJob


class FakeFollowup:
    def __init__(self):
        self.messages = []

    async def send(self, text):
        self.messages.append(text)


class FakeInteraction:
    def __init__(self):
        self.followup = FakeFollowup()


def make_job(number=1):
    return ReportJob(
        steam_id64=76561198000000000 + number,
        steam_name=f"Player{number}",
        server_name="Rustoria EU Long",
        requester_id=1,
        channel_id=2,
    )


def test_shared_queue_capacity_is_ten():
    assert jobs.MAX_PENDING_REPORTS == 10
    assert jobs.queue.maxsize == 10


@pytest.mark.asyncio
async def test_enqueue_returns_position_when_capacity_exists(monkeypatch):
    test_queue = asyncio.Queue(maxsize=2)
    monkeypatch.setattr(command_bot, "queue", test_queue)
    interaction = FakeInteraction()

    position = await command_bot.enqueue_or_reject(interaction, make_job())

    assert position == 1
    assert test_queue.qsize() == 1
    assert interaction.followup.messages == []


@pytest.mark.asyncio
async def test_full_queue_sends_busy_response_without_enqueuing(monkeypatch):
    test_queue = asyncio.Queue(maxsize=1)
    test_queue.put_nowait(make_job(1))
    monkeypatch.setattr(command_bot, "queue", test_queue)
    interaction = FakeInteraction()

    position = await command_bot.enqueue_or_reject(interaction, make_job(2))

    assert position is None
    assert test_queue.qsize() == 1
    assert "queue is full" in interaction.followup.messages[0].lower()
