# Slack setup — Invoice Watchdog

The watchdog posts two things to Slack, and nothing else:

- **Alerts** — one short line per catch, exactly as the pipeline wrote it
  (`Vendor · invoice · $ at risk · check name`, or `needs human review`).
  No contract prices, no clause text, no invoice lines, no dispute drafts.
- **Morning summary** — one line: invoices audited, failures, amount at
  risk, reviews needed, and the latest audit-log hash. Posting that hash
  daily makes the log tamper-evident beyond this machine.

Approvals stay on the dashboard. Nothing here sends email or disputes.

## 1. Workspace and channel

Join the workspace, then pick (or create) a channel, e.g. `#ap-watchdog`,
and invite the bot into it:

```
/invite @Invoice Watchdog
```

The bot can only post where it is a member. A channel ID (`C...`) is the
reliable address: open the channel and copy the ID from its URL
(`.../archives/C...`). A `#channel-name` also works for public channels.

## 2. Tokens — environment only, never in the repo

The Slack app's bot token and the channel go in the shell, on the machine
that runs the watchdog (the Dell). Nothing in this repo reads a `.env`
file, and no token may ever be committed:

```bash
export SLACK_BOT_TOKEN="paste-the-bot-token-here"
export SLACK_CHANNEL="C-paste-the-channel-id-here"
```

If a token was ever pasted into a chat log or a file, rotate it in the
Slack app settings after the demo — a token in a log is a token to replace.

The app token (Socket Mode) is **not** needed for this integration: posting
uses the bot token only. It would matter only for a future interactive
listener (e.g. approving from Slack); approvals today live on the dashboard.

## 3. Test it

```bash
python3 -m engine.slack test      # posts one "connection OK" line
python3 -m engine.slack pending   # posts queued alerts, marks them posted
python3 -m engine.slack summary   # posts the morning summary line
```

To test without touching Slack at all:

```bash
SLACK_DRY_RUN=1 python3 -m engine.slack test
```

## 4. Run it live

```bash
python3 demo.py --slack                       # demo: summary + alerts as phases land
python3 -m engine.pipeline --watch --slack   # always-on: each catch posts as it lands
```

Without `--slack`, or without the two variables set, everything works
exactly as before and alerts simply queue in `data/alerts.jsonl`.

## 5. Wifi off

Slack needs the internet; the audit does not. With wifi off, the pipeline
and dashboard keep working, alerts queue in `alerts.jsonl`, and
`python3 -m engine.slack pending` posts them when the network is back.
`data/alerts.jsonl` is gitignored, so the queue never lands in a commit.
