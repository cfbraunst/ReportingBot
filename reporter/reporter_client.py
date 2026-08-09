"""The reporter: your user account, filing reports in the target server.

Consumes jobs one at a time with randomized delays. Submission is gated behind
LIVE_SUBMIT so the whole path can be exercised without filing anything.
"""
import asyncio
import logging
import random
import time
from collections import deque

import selfcord
from selfcord.components import Button

from reporter.config import (
    USER_TOKEN, TARGET_GUILD_ID, TARGET_CHANNEL_ID, TICKET_MESSAGE_ID,
    TICKET_BUTTON_CUSTOM_ID, REPORT_REASON, LIVE_SUBMIT,
    MIN_DELAY_SECONDS, MAX_DELAY_SECONDS, MAX_REPORTS_PER_HOUR,
    MIN_SECONDS_BETWEEN_REPORTS,
)
from reporter.jobs import ReportJob, queue

log = logging.getLogger(__name__)

# Field custom_ids, from discovery. See discovery_output.json.
FIELD_USERNAME = "username_input"
FIELD_STEAMID = "steam64id_input"
FIELD_SERVER = "server_input"
FIELD_REASON = "reason_input"
FIELD_EVIDENCE = "evidence_input"

MAX_USERNAME = 50
MAX_SERVER = 50


class ReporterStopped(RuntimeError):
    """Raised when the worker must halt -- the target UI no longer matches."""


class Reporter(selfcord.Client):
    def __init__(self, notify) -> None:
        """`notify(channel_id, text)` reports outcomes back via the command bot."""
        super().__init__()
        self.notify = notify
        self._modal_waiter: asyncio.Future | None = None
        self._recent = deque()  # submission timestamps, for the hourly cap
        self._last_submit: float | None = None  # for the per-minute gap
        self._halted = False

    async def on_ready(self) -> None:
        log.info("Reporter online as %s", self.user)
        self.loop.create_task(self._worker())

    async def on_modal(self, modal) -> None:
        # Modals arrive asynchronously after a click, never as click()'s return.
        if self._modal_waiter and not self._modal_waiter.done():
            self._modal_waiter.set_result(modal)

    # -- queue worker -------------------------------------------------

    async def _worker(self) -> None:
        while True:
            job = await queue.get()
            try:
                if self._halted:
                    await self._notify_safe(
                        job, "⛔ Reporter is halted. Report not filed.")
                    continue
                await self._process(job)
            except ReporterStopped as e:
                self._halted = True
                log.error("Reporter halted: %s", e)
                await self._notify_safe(job, f"⛔ {e}")
            except Exception as e:
                log.exception("Report failed")
                await self._notify_safe(job, f"❌ Failed: {type(e).__name__}: {e}")
            finally:
                queue.task_done()

    async def _notify_safe(self, job: ReportJob, text: str) -> None:
        """Never let a failed notification kill the worker."""
        try:
            await self.notify(job.channel_id, f"<@{job.requester_id}> {text}")
        except Exception:
            log.exception("Failed to deliver notification: %s", text)

    async def _process(self, job: ReportJob) -> None:
        # Hourly cap: wait for a slot rather than halting, so a busy session
        # doesn't require a restart.
        wait = self.seconds_until_slot_free()
        if wait > 0:
            mins = wait / 60
            log.info("Hourly cap reached; waiting %.1f min for a slot.", mins)
            await self._notify_safe(
                job,
                f"⏳ Hourly cap reached ({MAX_REPORTS_PER_HOUR}/hr). "
                f"This report is queued and will be filed in about {mins:.0f} min."
            )
            await asyncio.sleep(wait)

        # Wait out the minimum gap since the last submission, then add jitter on
        # top -- randomized, never a fixed tick, since regular timing is the
        # loudest script tell.
        gap_remaining = 0.0
        if self._last_submit is not None:
            elapsed = time.monotonic() - self._last_submit
            gap_remaining = max(0.0, MIN_SECONDS_BETWEEN_REPORTS - elapsed)

        delay = gap_remaining + random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
        log.info("Waiting %.1fs before filing for %s (%.0fs of that is the "
                 "per-minute gap)", delay, job.steam_id64, gap_remaining)
        await asyncio.sleep(delay)

        # Count the gap from the attempt, not the success -- a run of failures
        # must not let the button be clicked without spacing.
        self._last_submit = time.monotonic()

        modal = await self._open_modal()
        self._fill(modal, job)

        if not LIVE_SUBMIT:
            log.warning("LIVE_SUBMIT is off -- filled but not submitted.")
            await self._notify_safe(
                job,
                f"🧪 **Dry run** -- form filled for **{job.steam_name}** "
                f"(`{job.steam_id64}`) on **{job.server_name}**, but not submitted. "
                f"Set `LIVE_SUBMIT=true` in .env to file for real."
            )
            return

        await modal.submit()
        self._recent.append(time.monotonic())
        log.info("Submitted report for %s", job.steam_id64)
        await self._notify_safe(
            job,
            f"✅ Report filed for **{job.steam_name}** "
            f"(`{job.steam_id64}`) on **{job.server_name}**."
        )

    # -- modal handling -----------------------------------------------

    async def _open_modal(self):
        guild = self.get_guild(TARGET_GUILD_ID)
        if guild is None:
            raise ReporterStopped("No longer a member of the target server.")

        channel = guild.get_channel(TARGET_CHANNEL_ID) or self.get_channel(TARGET_CHANNEL_ID)
        if channel is None:
            raise ReporterStopped("Target channel is no longer visible.")

        try:
            message = await channel.fetch_message(TICKET_MESSAGE_ID)
        except Exception as e:
            raise ReporterStopped(f"Ticket message {TICKET_MESSAGE_ID} is gone ({e}).")

        button = next(
            (
                c for row in message.components
                for c in getattr(row, "children", [])
                if isinstance(c, Button) and c.custom_id == TICKET_BUTTON_CUSTOM_ID
            ),
            None,
        )
        if button is None:
            raise ReporterStopped(
                f"Button '{TICKET_BUTTON_CUSTOM_ID}' not found -- the ticket tool changed."
            )

        self._modal_waiter = self.loop.create_future()
        await button.click()
        try:
            return await asyncio.wait_for(self._modal_waiter, timeout=15)
        except asyncio.TimeoutError:
            raise ReporterStopped("Clicked the button but no modal arrived within 15s.")
        finally:
            self._modal_waiter = None

    def _fill(self, modal, job: ReportJob) -> None:
        inputs = {}
        for row in getattr(modal, "components", []):
            kids = getattr(row, "children", None)
            for c in (kids if kids is not None else [row]):
                cid = getattr(c, "custom_id", None)
                if cid:
                    inputs[cid] = c

        expected = {FIELD_USERNAME, FIELD_STEAMID, FIELD_SERVER, FIELD_REASON}
        missing = expected - inputs.keys()
        if missing:
            raise ReporterStopped(f"Modal changed shape -- missing fields: {sorted(missing)}")

        inputs[FIELD_USERNAME].value = job.steam_name[:MAX_USERNAME]
        inputs[FIELD_STEAMID].value = str(job.steam_id64)
        inputs[FIELD_SERVER].value = job.server_name[:MAX_SERVER]
        inputs[FIELD_REASON].value = REPORT_REASON
        # Evidence is optional on this form; left blank deliberately.
        if FIELD_EVIDENCE in inputs:
            inputs[FIELD_EVIDENCE].value = ""

    # -- pacing --------------------------------------------------------

    def seconds_until_slot_free(self) -> float:
        """How long until the hourly cap allows another report. 0 if free now."""
        now = time.monotonic()
        cutoff = now - 3600
        while self._recent and self._recent[0] < cutoff:
            self._recent.popleft()
        if len(self._recent) < MAX_REPORTS_PER_HOUR:
            return 0.0
        # The oldest submission in the window has to age out.
        return (self._recent[0] + 3600) - now


async def start_reporter(notify) -> Reporter:
    client = Reporter(notify)
    asyncio.create_task(client.start(USER_TOKEN))
    return client
