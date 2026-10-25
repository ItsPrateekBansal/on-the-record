"""Invoice Watchdog — what the OpenClaw agent posts to Slack.

The pipeline queues one short line per catch in data/alerts.jsonl (no prices, no clauses).
The agent's skills read the queue, post each line, then mark them posted:

    python3 -m engine.alerts pending          # unposted alerts, one per line: <id>\t<text>
    python3 -m engine.alerts posted 3 4 5     # mark these ids as posted (or: posted all)
    python3 -m engine.alerts summary          # morning summary text, with the latest audit hash
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import audit_log  # noqa: E402
from engine.evidence import DATA_DIR  # noqa: E402


def _path(data_dir) -> Path:
    return Path(data_dir) / "alerts.jsonl"


def _read(data_dir) -> list[dict]:
    p = _path(data_dir)
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def pending(data_dir=DATA_DIR) -> list[tuple[int, str]]:
    return [(i, a["text"]) for i, a in enumerate(_read(data_dir), 1) if not a.get("posted")]


def mark_posted(ids, data_dir=DATA_DIR) -> int:
    alerts, n = _read(data_dir), 0
    for i, a in enumerate(alerts, 1):
        if (ids == "all" or i in ids) and not a.get("posted"):
            a["posted"], n = True, n + 1
    _path(data_dir).write_text("".join(json.dumps(a) + "\n" for a in alerts))
    if n:
        audit_log.append(data_dir, "alerts_posted", None, count=n)
    return n


def summary(data_dir=DATA_DIR) -> str:
    rows = [json.loads(p.read_text()) for p in Path(data_dir).glob("results/*/*.json")]
    fails = [r for r in rows if r["status"] == "FAIL"]
    review = [r for r in rows if r["status"] == "NEEDS_REVIEW"]
    at_risk = sum(r["at_risk"] for r in fails)
    text = f"Invoice Watchdog: audited {len(rows)} invoices. {len(fails)} failed, ${at_risk:,.2f} at risk."
    if review:
        text += f" {len(review)} need human review (${sum(r['amount_under_review'] for r in review):,.2f})."
    ok, n, _ = audit_log.verify(data_dir)
    text += f" Audit log: {n} entries, {'chain intact' if ok else 'CHAIN BROKEN'}, latest hash {audit_log.latest_hash(data_dir)[:12]}."
    return text


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "pending"
    if cmd == "pending":
        for i, text in pending():
            print(f"{i}\t{text}")
    elif cmd == "posted":
        args = sys.argv[2:]
        print(f"marked {mark_posted('all' if args == ['all'] else {int(a) for a in args})} posted")
    elif cmd == "summary":
        print(summary())
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
