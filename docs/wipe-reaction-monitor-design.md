# Wipe Reaction Monitor Design

## Goal

Use the existing ReportingBot Discord bot and Proxmox LXC container to identify
people who choose two or more of the three wipe attendance reactions on a single
message. The choices shown in the reference screenshot are ✅ (on time), ⏰
(late), and ❌ (not playing). Notify a separate admin channel promptly, and let
an administrator request a current check.

## Agreed Behavior

- Configure one wipe channel and one admin alert channel in the server where the
  bot is already present. The bot watches any message in the wipe channel that
  has all three specified reaction emojis. Text in the message does not make it
  eligible; the emojis must be reactions on that message.
- Count distinct choices per user on each message. Two or three distinct choices
  are an overlap. Multiple reaction modes for the same emoji still count as one
  choice. Other emojis do not count. Ignore the bot's own reactions, if any.
- On a relevant reaction addition, inspect the message's current reaction
  users. For each newly detected overlap, send one alert to the admin channel
  with the person's identity, their selected choices, and a jump link to the
  message. Suppress mention pings in the alert. Scanning all current users
  also catches overlaps that existed before the third option appeared.
- Reacting on an older eligible message can still produce an automatic alert.
- `/wipe-check` is restricted to server administrators. It searches the wipe
  channel newest first, up to 1,000 messages, for the most recent eligible
  message. It privately shows the current overlaps for that message, or clearly
  says that no eligible message was found. A check always reads current Discord
  data; it does not reuse past alert results.
- At startup, perform that same newest-message search and alert for existing
  overlaps that have not already been alerted. This covers reactions added
  while the bot was offline on the newest eligible message.
- When an overlap is removed, clear its active alert state. If that user later
  chooses two or more options again on the same message, send a new alert.
  The on-demand result always reflects the current state.

## Approach and Data Flow

Extend `reporter.command_bot.CommandBot`, which already runs in `main.py`, with
uncached reaction add/remove handlers and the `/wipe-check` slash command. Keep
the overlap calculation and Discord fetching in a focused wipe reaction module
so the reporting queue and reporter client have no new dependency on this
feature.

For a relevant reaction event, filter by configured guild, channel, and emoji
before fetching the message. Require all three emoji reactions to be present,
then enumerate reaction users and calculate every user's distinct choices from
fresh data. Serialize checks for the same message so near-simultaneous events
cannot create duplicate alerts. On reaction removal or reaction clear, recheck
active overlaps on that message and clear those that no longer qualify. If the
message no longer has all three options, clear its active overlap state.

For startup and `/wipe-check`, walk message history from newest to oldest until
the first eligible message is found or 1,000 messages have been examined. Defer
the slash command response while Discord data is fetched. Enumerate the users
for all three choices and return only the users whose distinct-choice count is
at least two.

Use the ordinary bot account for this feature. It needs View Channel and Read
Message History in the wipe channel, and View Channel and Send Messages in the
admin channel. Enable the reaction gateway intent. Message content and member
privileged intents are not required for the agreed behavior.

## Alert State and Container Storage

Persist active alert keys by guild, message, and user in a small SQLite database
using Python's standard library. Store the selected choices and a timestamp for
diagnosis, but use fresh Discord reactions for decisions. Mark an overlap active
only after Discord accepts the admin alert. A failed send remains retryable.
The state prevents normal service restarts from reposting the same existing
overlap. A crash between sending an alert and recording it can still produce a
repeat; Discord messages and the local database cannot be committed atomically.

Add `StateDirectory=reportingbot` to the existing systemd service so the bot can
write state under `/var/lib/reportingbot` while `ProtectSystem=strict` remains
enabled. Use systemd's `STATE_DIRECTORY` environment variable for the deployed
database path, with `WIPE_STATE_PATH` as a local development override whose
default is gitignored.
The existing container runs the bot as `reportingbot.service`; no second bot
process or container is needed.

## Configuration and Failure Handling

Add `WIPE_GUILD_ID`, `WIPE_CHANNEL_ID`, and `WIPE_ADMIN_CHANNEL_ID` to the
configuration and setup instructions. Validate positive IDs and that the source
and alert channels belong to the configured guild. Keep these settings separate
from the reporting credentials so a wipe-monitor configuration or permission
failure is reported clearly without stopping the reporting feature.

If a channel is missing, permissions are insufficient, Discord returns an
error, or the state database cannot be opened, log the specific feature error
without printing secrets. `/wipe-check` should tell its caller that the check
could not finish. Do not mark an alert sent when sending fails. Avoid claiming
that no overlaps exist when fetching reaction users was incomplete.

## Verification and Rollout

Offline tests will cover eligibility, distinct-choice counting, two- and
three-choice overlaps, unrelated emoji, removals, duplicate event delivery,
startup alerts across restart, the newest eligible message, the 1,000-message
limit, and failed Discord operations. Tests will mock Discord access and never
submit a report.

Update the existing service unit and configuration example, deploy into the
same container, and verify its startup status and logs. With a harmless test
message bearing the three reactions, verify one automatic alert, an
administrator-only `/wipe-check` result, removal and re-addition behavior, and
no repeated alert after an ordinary service restart. Verify `/report` still
registers and operates independently of the new feature.

## Scope Boundary

This design covers the first requested feature only. The second unrelated bot
feature will be planned separately and can share the same bot process and
container.
