# Setup

Step-by-step, from a fresh clone to a running bot. Steps 1–8 involve no real
reports; nothing is ever filed until you deliberately change one setting in
[step 10](#10-going-live).

**Before you start,** read the
[Account risk](README.md#account-risk) section. The reporter drives a Discord
**user account**, which breaks Discord's Terms of Service and can get that
account permanently terminated. That risk is yours to accept, and it does not
go away because the automation is careful.

---

## 1. Prerequisites

- **Python 3.11 or newer** (3.13 works; see the note in the README)
- **Git**
- A **Discord server you control**, to host the `/report` command
- A **Discord account** that can already see the report button you want to
  drive, and that is allowed to use it

Check your Python:

```bash
python --version
```

## 2. Clone the repository

```bash
git clone https://github.com/cfbraunst/ReportingBot.git
cd ReportingBot
```

## 3. Create a virtual environment

Linux / macOS:

```bash
python -m venv venv
source venv/bin/activate
```

Windows (PowerShell):

```bash
python -m venv venv
venv\Scripts\Activate.ps1
```

Every later `python` command assumes this environment is active. If you would
rather not activate it, call the interpreter directly — `venv/bin/python` on
Linux and macOS, `venv/Scripts/python.exe` on Windows.

## 4. Install dependencies

```bash
python -m pip install -r requirements.txt
```

This pulls `selfcord` from a **Git commit**, not PyPI, so the install needs
network access to GitHub and takes longer than a normal `pip install`. The PyPI
package called `selfcord.py` is an unrelated project — do not substitute it.

Confirm the install:

```bash
python -m pytest
```

All tests should pass. They are fully offline: no Discord or Steam calls.

## 5. Create your `.env`

```bash
cp .env.example .env
```

`.env` is gitignored. Never commit it, and never paste its contents anywhere.
Fill it in as you work through the next steps.

### 5a. STEAM_API_KEY

Sign in at <https://steamcommunity.com/dev/apikey>, register a key (any domain
works — it is not validated for this use), and copy it.

```
STEAM_API_KEY=your_key_here
```

### 5b. COMMAND_BOT_TOKEN

This is an ordinary Discord bot, and it does the *safe* half of the work: it
owns the `/report` command and never touches the target server.

1. Go to <https://discord.com/developers/applications> → **New Application**.
2. Open the **Bot** tab → **Reset Token** → copy the token.
3. No privileged intents are needed. The bot reads interactions, not messages.
4. Open **OAuth2 → URL Generator**, tick `bot` and `applications.commands`,
   and give it **Send Messages** permission.
5. Open the generated URL and invite the bot to *your own* server.

```
COMMAND_BOT_TOKEN=your_bot_token_here
```

### 5c. USER_TOKEN

The token of the Discord **account** that will fill in the form. It belongs to
a human account, not a bot application.

> **A Discord account token is equivalent to full access to that account** —
> it bypasses both the password and two-factor authentication. Treat it exactly
> like a password: never share it, never commit it, never paste it into a
> website, a Discord message, or an issue report. Anyone asking you for one is
> trying to steal the account.

You retrieve it from your own logged-in Discord session: the token is sent as
the `Authorization` header on requests to Discord's API, visible in the browser
developer tools' network panel. Copy it from there into `.env`:

```
USER_TOKEN=your_account_token_here
```

If the token stops working later, that is expected — see
[Rotating or revoking the token](#rotating-or-revoking-the-token).

## 6. Point it at a target

No target ships with this repository. You supply one, and you are responsible
for whether you are entitled to automate against it.

**Enable Developer Mode** in Discord: *Settings → Advanced → Developer Mode*.
You can now right-click things and **Copy ID**.

1. Right-click the **server** holding the report button → Copy Server ID.
2. Right-click the **channel** holding it → Copy Channel ID.

```
TARGET_GUILD_ID=000000000000000000
TARGET_CHANNEL_ID=000000000000000000
```

Then let `discover.py` find the rest. It logs in, reads the last 25 messages in
that channel, and prints every button it sees. **It only reads** — it never
clicks a button or opens a form:

```bash
python discover.py
```

Output looks like this:

```
TICKET_MESSAGE_ID=000000000000000000
  from SomeTicketBot -- 1 button(s):
    TICKET_BUTTON_CUSTOM_ID=create-report    # 'Create New Report'
```

Copy the pair that matches the button you mean into `.env`:

```
TICKET_MESSAGE_ID=000000000000000000
TICKET_BUTTON_CUSTOM_ID=create-report
```

If it finds no buttons, raise `SCAN_LIMIT` in `discover.py` or double-check the
channel ID.

## 7. Check the form fields match

The reporter fills five fields by `custom_id`, hardcoded in
`reporter/reporter_client.py` and listed in the
[Form fields](README.md#form-fields) table. They were captured from one
specific report form.

If your target's form is different, edit those constants — and `REPORT_REASON`
in `reporter/config.py` — to match. You do not have to guess: the reporter
**halts instead of submitting** when the modal lacks the fields it expects, and
the log names the ones that are missing.

While you are in `reporter/config.py`, set `SERVER_CHOICES` to the servers you
actually play on. They become the `/report` dropdown.

## 8. Dry run

Confirm `LIVE_SUBMIT=false` in `.env`, then:

```bash
python dryrun.py
```

This pushes a placeholder job straight into the queue, so the whole reporter
path runs: it logs in, clicks the button, receives the form, fills every field,
and **stops without submitting**. It refuses to run at all if `LIVE_SUBMIT` is
on.

Expect a `Dry run` line. If it halts instead, the message tells you what didn't
match — usually a stale `TICKET_MESSAGE_ID` or a changed form.

## 9. Start it

```bash
python main.py
```

Both clients come up in one process. In your own server, run:

```
/report steam_id:76561198012345678 server:"EU Long"
```

With `LIVE_SUBMIT` still off, you get a queued confirmation and then a dry-run
notice. This is the full production path with the last step disabled — a good
state to leave it in while you get familiar with it.

## 10. Going live

Only now does anything get filed. In `.env`:

```
LIVE_SUBMIT=true
```

Restart the process. It logs a warning on startup, so you cannot flip this and
forget.

**What this means.** Reports go into a third-party moderation system. Where that
system is a cross-server anticheat network, one filed report can get an account
banned on every server using it. A wrong Steam ID therefore has real
consequences for a real person who did nothing. Verify the ID before you file.

Pacing is set in `reporter/config.py`: one report at a time, a minimum gap of
60 seconds plus random jitter, and a cap of 5 per hour. Raising these makes the
account look more scripted and increases the chance that both Discord and the
receiving operators notice.

## Rotating or revoking the token

Logging out of Discord everywhere, or changing that account's password,
invalidates `USER_TOKEN` immediately and stops the reporter. **That is the kill
switch** — use it if the bot misbehaves or the token leaks.

After a deliberate rotation, put the new token in `.env` and restart.

## Running as a systemd service

`deploy/reportingbot.service` is a hardened unit file: no new privileges, a
read-only system, an empty capability set. On a Linux host:

1. Create an unprivileged account and a checkout it can read:

   ```bash
   sudo useradd --system --home /opt/reportingbot --shell /usr/sbin/nologin reportingbot
   sudo git clone https://github.com/cfbraunst/ReportingBot.git /opt/reportingbot
   sudo python3 -m venv /opt/reportingbot/.venv
   sudo /opt/reportingbot/.venv/bin/pip install -r /opt/reportingbot/requirements.txt
   ```

2. Install your `.env` so **only** that account can read it:

   ```bash
   sudo install -o reportingbot -g reportingbot -m 600 /path/to/your/.env /opt/reportingbot/.env
   sudo chown -R reportingbot:reportingbot /opt/reportingbot
   ```

3. Adjust `WorkingDirectory` and `ExecStart` in the unit if your paths differ,
   then install and start it:

   ```bash
   sudo cp /opt/reportingbot/deploy/reportingbot.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now reportingbot
   ```

4. Check on it:

   ```bash
   systemctl status reportingbot
   journalctl -u reportingbot -f
   ```

Pending reports live in memory, so a restart discards them. The queue holds at
most ten.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `Missing or invalid required configuration` | Named keys are blank in `.env`. Startup validates before connecting. |
| `USER_TOKEN was rejected` | Token expired or was revoked — a logout-everywhere or password change does this. Get a fresh one. |
| `Not a member of the target server` | That account can no longer see `TARGET_GUILD_ID`. |
| `Ticket message ... is gone` | The message was deleted or replaced. Re-run `discover.py`. |
| `Button ... not found` | The ticket tool was reconfigured. Re-run `discover.py`. |
| `Modal changed shape -- missing fields` | The form changed. Update the field constants — see [step 7](#7-check-the-form-fields-match). |
| `The report queue is full` | Ten reports already pending; the reporter drains a few per hour. |
| `ModuleNotFoundError: selfcord` | `pip install -r requirements.txt` didn't finish, or the wrong environment is active. |
| `ModuleNotFoundError: audioop` | Python 3.13+ without `audioop-lts`. Reinstall from `requirements.txt`. |

The reporter is deliberately fragile in one direction: when the target's UI
stops matching what it expects, it **halts** rather than retrying or guessing.
A halted reporter is working as designed.
