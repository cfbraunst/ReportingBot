# ReportingBot

Turns a pasted Steam ID into a filed cheater report, so reports can be made
mid-game without clicking through Discord.

**Flow:** someone runs `/report` in your server → the Steam name is looked up →
the job is queued → a Discord account opens the report form in the target
server and fills it in.

> **Read this first.** The reporter drives a **Discord user account**, which
> breaks Discord's Terms of Service and can get that account terminated. It
> files reports into a third-party moderation system, where a wrong Steam ID
> has real consequences for whoever owns it. See
> [Account risk](#account-risk) and [LIVE_SUBMIT](#live_submit) below.
> No target server ships with this repo — you supply your own.

## Setup

Step-by-step instructions, including how to obtain every credential, are in
**[SETUP.md](SETUP.md)**. The short version:

```bash
python -m venv venv
venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
cp .env.example .env                                          # then fill it in
```

`.env` needs:

| Key | What it is |
|---|---|
| `STEAM_API_KEY` | From <https://steamcommunity.com/dev/apikey> |
| `COMMAND_BOT_TOKEN` | Bot token; the bot must be in your server |
| `USER_TOKEN` | A Discord account token, for the reporter |
| `TARGET_GUILD_ID` / `TARGET_CHANNEL_ID` | Where the report button lives |
| `TICKET_MESSAGE_ID` / `TICKET_BUTTON_CUSTOM_ID` | From `discover.py` |
| `LIVE_SUBMIT` | `false` = fill but never submit. See below. |

## Running

```bash
python discover.py    # read-only: find the ticket message and button IDs
python main.py        # both clients, one process
python dryrun.py      # exercise the full path, submit nothing
python -m pytest      # test suite
```

On Windows, use `venv/Scripts/python.exe` in place of `python`.

## Usage

```
/report steam_id:76561198012345678 server:"EU Long"
/report steam_id:steamcommunity.com/id/somename server:Custom custom_server:My Server
```

`steam_id` accepts SteamID64, profile and vanity URLs, `STEAM_0:...`, and `[U:1:...]`.

The dropdown presets live in `SERVER_CHOICES` in `reporter/config.py`. Edit them
to match the servers you play on.

## LIVE_SUBMIT

While `false`, the reporter does everything except submit: clicks the button,
receives the modal, fills all fields, then stops and reports a dry run. Set it
to `true` only when you intend to file real reports.

A report filed into a cross-server anticheat network can get someone banned
everywhere that network is used, so a wrong Steam ID has real consequences for
whoever owns it. Verify the ID before you flip this.

## Account risk

Automating a user account is against Discord's ToS and can get the account
terminated. Operators of the receiving system also watch for report spam. The
pacing limits reduce but do not eliminate either risk.

Logging out of Discord everywhere, or changing that account's password,
invalidates `USER_TOKEN` and stops the reporter — that is the kill switch.

## Design notes

**One process, two clients.** `discord.py` (the bot) and `selfcord`
(the user account) coexist because selfcord is installed from the `renamed`
branch, which imports as `selfcord` instead of `discord`. It is **not** on
PyPI — the PyPI package named `selfcord.py` is an unrelated project. The pin in
`requirements.txt` is a commit, because that branch tracks development.

**Modals arrive asynchronously.** `button.click()` returns `None`; the modal
comes later via the `on_modal` event. Anything waiting on the return value hangs.

**Pacing** exists to keep the account from looking scripted: one report at a
time, randomized delays, and an hourly cap. Tune in `reporter/config.py`.

**The reporter halts** rather than retrying if the button vanishes, the message
is deleted, or the modal changes shape — a reconfigured ticket tool should stop
the bot, not make it submit malformed reports.

**Python versions.** Developed on Python 3.11; also runs on 3.13.
`audioop-lts` is installed only on 3.13+ because the pinned self-account
library still imports the standard-library module removed in Python 3.13.

## Form fields

The reporter fills a five-field modal. These `custom_id`s were captured from
the form it was built against and are hardcoded in
`reporter/reporter_client.py`:

| Field | custom_id | Filled with |
|---|---|---|
| Player's username | `username_input` | Steam display name (≤50 chars) |
| Player's Steam64ID | `steam64id_input` | Normalized SteamID64 |
| What server | `server_input` | Choice or custom (≤50 chars) |
| What were they doing | `reason_input` | `REPORT_REASON` from config |
| Evidence | `evidence_input` | Empty — optional on the form |

**If your target's form differs, update those constants.** The reporter halts
rather than submitting when the modal doesn't match.

Note the library reported *all five* fields as required; the rendered form
showed only four asterisks. The form is authoritative. If a future version
rejects an empty Evidence field, that's the first place to look.

## Running as a service

`deploy/reportingbot.service` is a hardened systemd unit. Point
`WorkingDirectory` and `ExecStart` at your checkout, create the unprivileged
account it runs as, then:

```bash
systemctl status reportingbot
systemctl restart reportingbot
journalctl -u reportingbot -n 100 --no-pager
journalctl -u reportingbot -f
```

Pending reports are in memory. Restarting the service discards them. The queue
accepts at most ten pending reports.

Deployment details are in [SETUP.md](SETUP.md#running-as-a-systemd-service).
