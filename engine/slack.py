"""Invoice Watchdog — post the queued alerts and the morning summary to Slack.

The pipeline never sends anything itself: it queues short alert lines in
data/alerts.jsonl (step 11) and the morning summary is built by
engine.alerts.summary(). This module is the only thing that talks to Slack,
and it posts exactly those lines, word for word. It never posts contract
prices, clause text, invoice lines or dispute drafts — those stay on the
local dashboard.

Configuration comes from the environment, or from a repo-root .env file
(gitignored, local to the machine running the watchdog — never committed):

    SLACK_BOT_TOKEN   bot token for the Slack app
    SLACK_CHANNEL     channel ID (C...) preferred; a #channel name also works
    SLACK_DRY_RUN=1   print instead of posting (for testing, no network)

CLI:

    python3 -m engine.slack pending   # post unposted alerts, mark them posted
    python3 -m engine.slack summary   # post the morning summary line
    python3 -m engine.slack test      # post one connection-test line

Stdlib only, like the rest of the engine: no new dependency. If Slack is
unreachable (wifi off), nothing here fails the audit — the alerts simply
stay queued in alerts.jsonl and post later with `pending`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import alerts  # noqa: E402
from engine.evidence import DATA_DIR  # noqa: E402

API_URL = "https://slack.com/api/chat.postMessage"


class NotConfigured(Exception):
    pass


class SlackError(Exception):
    pass


def _load_dotenv():
    """Fill missing settings from a repo-root .env file, if one exists.

    .env is gitignored: it lives on the machine running the watchdog and is
    never committed or pushed. Real environment variables always win over
    .env, and values are never printed or logged.
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    try:
        lines = env_path.read_text().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("\"'")
        if key in ("SLACK_BOT_TOKEN", "SLACK_CHANNEL", "SLACK_DRY_RUN"):
            os.environ.setdefault(key, value)


def config():
    """(token, channel) from the environment (or repo-root .env), or raise NotConfigured."""
    _load_dotenv()
    token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    channel = os.environ.get("SLACK_CHANNEL", "").strip()
    missing = [n for n, v in (("SLACK_BOT_TOKEN", token), ("SLACK_CHANNEL", channel)) if not v]
    if missing:
        raise NotConfigured(f"missing {', '.join(missing)}; see docs/SLACK_SETUP.md")
    return token, channel


def _http_post(payload, token):
    if os.environ.get("SLACK_DRY_RUN") == "1":
        print(f"[slack dry-run] {payload['channel']}: {payload['text']}")
        return {"ok": True, "ts": "dry-run"}
    req = urllib.request.Request(API_URL, data=json.dumps(payload).encode(),
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise SlackError(f"Slack HTTP {exc.code}") from exc
    except OSError as exc:
        raise SlackError(f"could not reach Slack ({exc})") from exc


def post_message(text, token=None, channel=None):
    """Post one message. Returns the Slack response; raises SlackError if refused."""
    if token is None or channel is None:
        env_token, env_channel = config()
        token = token or env_token
        channel = channel or env_channel
    resp = _http_post({"channel": channel, "text": text}, token)
    if not resp.get("ok"):
        raise SlackError(f"Slack refused the message ({resp.get('error', 'unknown error')})")
    return resp


def post_pending(data_dir=DATA_DIR):
    """Post every unposted alert; mark only the ones Slack accepted.

    Returns (posted_ids, failed) where failed is [(alert_id, error), ...].
    A failed alert stays queued and is retried on the next run.
    """
    token, channel = config()
    posted, failed = [], []
    for alert_id, text in alerts.pending(data_dir):
        try:
            post_message(text, token, channel)
        except SlackError as exc:
            failed.append((alert_id, str(exc)))
        else:
            posted.append(alert_id)
    if posted:
        alerts.mark_posted(set(posted), data_dir)
    return posted, failed


def post_summary(data_dir=DATA_DIR):
    token, channel = config()
    post_message(alerts.summary(data_dir), token, channel)
    return True


def main():
    ap = argparse.ArgumentParser(description="Post Invoice Watchdog alerts to Slack")
    ap.add_argument("command", choices=["pending", "summary", "test"])
    ap.add_argument("--data", default=str(DATA_DIR), help="data folder (default: repo data/)")
    args = ap.parse_args()
    data_dir = Path(args.data)
    try:
        if args.command == "pending":
            posted, failed = post_pending(data_dir)
            print(f"posted {len(posted)} alert(s)" + (f"; {len(failed)} failed" if failed else ""))
            for i, err in failed:
                print(f"  alert {i} failed: {err}")
            return 1 if failed else 0
        if args.command == "summary":
            post_summary(data_dir)
            print("posted morning summary")
            return 0
        post_message("Invoice Watchdog: Slack connection OK — alerts and morning summaries will arrive here.")
        print("posted connection test")
        return 0
    except NotConfigured as exc:
        print(f"Slack not configured: {exc}")
        return 2
    except SlackError as exc:
        print(f"Slack error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
