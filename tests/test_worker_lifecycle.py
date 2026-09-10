import asyncio

import pytest

from reporter.reporter_client import Reporter


@pytest.mark.asyncio
async def test_ensure_worker_reuses_live_task():
    reporter = Reporter.__new__(Reporter)
    reporter._worker_task = None
    release = asyncio.Event()

    async def worker():
        await release.wait()

    reporter._worker = worker
    first = reporter._ensure_worker()
    second = reporter._ensure_worker()

    assert second is first
    release.set()
    await first


@pytest.mark.asyncio
async def test_ensure_worker_replaces_completed_task():
    reporter = Reporter.__new__(Reporter)
    reporter._worker_task = None

    async def worker():
        return None

    reporter._worker = worker
    first = reporter._ensure_worker()
    await first
    second = reporter._ensure_worker()

    assert second is not first
    await second


@pytest.mark.asyncio
async def test_ensure_worker_replaces_failed_task():
    reporter = Reporter.__new__(Reporter)
    reporter._worker_task = None
    calls = 0

    async def worker():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("worker stopped")

    reporter._worker = worker
    first = reporter._ensure_worker()
    with pytest.raises(RuntimeError, match="worker stopped"):
        await first
    second = reporter._ensure_worker()

    assert second is not first
    await second
