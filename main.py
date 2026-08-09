"""Entry point. Runs the command bot and the reporter in one process."""
import asyncio
import logging

from reporter.command_bot import CommandBot
from reporter.config import COMMAND_BOT_TOKEN, USER_TOKEN, LIVE_SUBMIT
from reporter.reporter_client import Reporter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


async def main() -> None:
    if not COMMAND_BOT_TOKEN or not USER_TOKEN:
        raise SystemExit("COMMAND_BOT_TOKEN and USER_TOKEN must both be set in .env")

    bot = CommandBot()

    async def notify(channel_id: int, text: str) -> None:
        """Reporter results go back through the bot, not the user account."""
        channel = bot.get_channel(channel_id)
        if channel is None:
            log.warning("Can't reach channel %s to report: %s", channel_id, text)
            return
        await channel.send(text)

    reporter = Reporter(notify)

    if LIVE_SUBMIT:
        log.warning("LIVE_SUBMIT is ON -- reports will be filed for real.")
    else:
        log.info("LIVE_SUBMIT is off -- dry run; forms are filled but never submitted.")

    await asyncio.gather(
        bot.start(COMMAND_BOT_TOKEN),
        reporter.start(USER_TOKEN),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down.")
