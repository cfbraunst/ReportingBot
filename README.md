# ReportingBot

Turns a pasted Steam ID into a filed cheater report, so reports can be made
mid-game without clicking through Discord.

**Flow:** someone runs `/report` in your server → the Steam name is looked up →
the job is queued → your user account opens the report form in the Rust server
and fills it in.

## Setup

```bash
python -m venv venv
venv/Scripts/python.exe -m pip install -r requirements.txt
cp .env.example .env      # then fill it in
```

`.env` needs:

| Key | What it is |
|---|---|
| `STEAM_API_KEY` | From <https://steamcommunity.com/dev/apikey> |
| `COMMAND_BOT_TOKEN` | Bot token; the bot must be in your server |
| `USER_TOKEN` | Your account token, for the reporter |
| `LIVE_SUBMIT` | `false` = fill but never submit. See below. |

Everything else is already filled in from discovery.

## Running

```bash
venv/Scripts/python.exe main.py     # both clients, one process
venv/Scripts/python.exe dryrun.py   # exercise the full path, submit nothing
venv/Scripts/python.exe -m pytest   # 24 tests
```

## Usage

```
/report steam_id:76561198012345678 server:"Rustoria EU Long"
/report steam_id:steamcommunity.com/id/somename server:Custom custom_server:My Server
```

`steam_id` accepts SteamID64, profile and vanity URLs, `STEAM_0:...`, and `[U:1:...]`.

## LIVE_SUBMIT

While `false`, the reporter does everything except submit: clicks the button,
receives the modal, fills all fields, then stops and reports a dry run. Set it
to `true` only when you intend to file real reports.

Reports go to Peacekeeper, a cross-server anticheat network. A filed report can
get someone banned across every server using it, so a wrong Steam ID has real
consequences for whoever owns it.

## Design notes

**One process, two clients.** `discord.py` (the bot) and `selfcord`
(the user account) coexist because selfcord is installed from the `renamed`
branch, which imports as `selfcord` instead of `discord`. It is **not** on
PyPI — the PyPI package named `selfcord.py` is an unrelated project. The pin in
`requirements.txt` is a commit, because that branch tracks development.

**Modals arrive asynchronously.** `button.click()` returns `None`; the modal
comes later via the `on_modal` event. Anything waiting on the return value hangs.

**Pacing** exists to keep the account from looking scripted: one report at a
time, randomized 4–15s delays, and a 10/hour cap. Tune in `reporter/config.py`.

**The reporter halts** rather than retrying if the button vanishes, the message
is deleted, or the modal changes shape — a reconfigured ticket tool should stop
the bot, not make it submit malformed reports.

## Form fields

Captured from the live modal (`discovery_output.json`):

| Field | custom_id | Filled with |
|---|---|---|
| Player's username | `username_input` | Steam display name (≤50 chars) |
| Player's Steam64ID | `steam64id_input` | Normalized SteamID64 |
| What Rust server | `server_input` | Choice or custom (≤50 chars) |
| What were they doing | `reason_input` | `"Cheating/Ban Evading"` |
| Evidence | `evidence_input` | Empty — optional on the form |

Note the library reported *all five* as required; the rendered form shows only
four asterisks. The form is authoritative. If a future version rejects an empty
Evidence field, that's the first place to look.

## Account risk

Automating a user account is against Discord's ToS and can get the account
terminated. Peacekeeper's operators also watch for report spam. The pacing
limits reduce but do not eliminate either risk.

Logging out of Discord everywhere, or changing your password, invalidates
`USER_TOKEN` and stops the reporter — that is the kill switch.
