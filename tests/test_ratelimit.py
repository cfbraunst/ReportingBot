"""Tests for the hourly cap. Time is faked -- no sleeping in tests."""
import time

import pytest

from reporter.reporter_client import Reporter
from reporter.config import MAX_REPORTS_PER_HOUR


@pytest.fixture
def limiter():
    r = Reporter.__new__(Reporter)
    from collections import deque
    r._recent = deque()
    r._last_submit = None
    return r


def test_free_when_nothing_filed(limiter):
    assert limiter.seconds_until_slot_free() == 0.0


def test_free_below_the_cap(limiter):
    now = time.monotonic()
    for i in range(MAX_REPORTS_PER_HOUR - 1):
        limiter._recent.append(now - i)
    assert limiter.seconds_until_slot_free() == 0.0


def test_blocks_at_the_cap(limiter):
    now = time.monotonic()
    for i in range(MAX_REPORTS_PER_HOUR):
        limiter._recent.append(now - i)
    wait = limiter.seconds_until_slot_free()
    assert wait > 0
    # The oldest is the newest-1 entries old, so the wait is just under an hour.
    # The upper bound carries a tolerance because seconds_until_slot_free()
    # computes (entry + 3600) - now, and that rounds a hair above 3600 for some
    # float values of time.monotonic().
    assert 3500 < wait <= 3600 + 1e-6


def test_wait_shrinks_as_entries_age(limiter):
    now = time.monotonic()
    # Oldest was 50 minutes ago -- 10 minutes left before it ages out.
    limiter._recent.append(now - 3000)
    for i in range(MAX_REPORTS_PER_HOUR - 1):
        limiter._recent.append(now - i)
    wait = limiter.seconds_until_slot_free()
    assert 550 < wait < 650  # ~600s


def test_expired_entries_are_dropped(limiter):
    now = time.monotonic()
    for _ in range(MAX_REPORTS_PER_HOUR):
        limiter._recent.append(now - 4000)  # all older than an hour
    assert limiter.seconds_until_slot_free() == 0.0
    assert len(limiter._recent) == 0


def test_cap_is_five():
    # The user asked for 5/hour specifically; guard against silent drift.
    assert MAX_REPORTS_PER_HOUR == 5


def test_minimum_gap_is_one_minute():
    from reporter.config import MIN_SECONDS_BETWEEN_REPORTS
    assert MIN_SECONDS_BETWEEN_REPORTS == 60
