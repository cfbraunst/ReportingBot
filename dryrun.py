"""End-to-end dry run: opens the real form, fills it, submits nothing.

Bypasses the command bot and pushes a job straight into the queue, so the
reporter path is exercised exactly as it would be in production.
"""
import asyncio
import logging
import sys

from reporter.config import USER_TOKEN, LIVE_SUBMIT
from reporter.jobs import ReportJob, queue
from reporter.reporter_client import Reporter

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")


async def main() -> None:
    if LIVE_SUBMIT:
        raise SystemExit("LIVE_SUBMIT is on -- refusing to run a 'dry' run.")

    results = []

    async def notify(channel_id: int, text: str) -> None:
        results.append(text)
        # Windows consoles are often cp1252; emoji in the message must not crash us.
        safe = text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
            sys.stdout.encoding or "utf-8", errors="replace"
        )
        print(f"\n>>> {safe}\n")

    reporter = Reporter(notify)
    asyncio.create_task(reporter.start(USER_TOKEN))

    await asyncio.sleep(8)  # let the gateway connect

    # Placeholder values -- the form is filled in memory and never submitted,
    # so these never reach anyone. Swap in a real ID only if you need to check
    # the Steam lookup path too.
    await queue.put(ReportJob(
        steam_id64=76561197960287930,
        steam_name="TestUser",
        server_name="Rustoria EU Long",
        requester_id=0,
        channel_id=0,
    ))
    print("Job queued. Waiting for the reporter to open and fill the form...")

    for _ in range(60):
        if results:
            break
        await asyncio.sleep(1)

    if not results:
        print("Timed out with no result.")
    await reporter.close()


if __name__ == "__main__":
    asyncio.run(main())
