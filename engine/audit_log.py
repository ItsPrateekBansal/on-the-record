"""Invoice Watchdog — tamper-evident audit log (hash-chained JSONL).

Every pipeline step appends one line to data/audit_log.jsonl. Each entry stores the hash of the
previous entry, so changing or deleting any past entry breaks the chain from that point on.
Tamper-evident, not tamper-proof: rewriting the whole file is still possible, which is why the
latest hash should also be posted somewhere else (e.g. the daily Slack summary).

Usage:
    from engine.audit_log import append, verify
    append(data_dir, "checked", "INV-B-5520", status="FAIL", at_risk=720.0)
    ok, count, problem = verify(data_dir)
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64


def _path(data_dir) -> Path:
    return Path(data_dir) / "audit_log.jsonl"


def _hash(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def read(data_dir) -> list[dict]:
    path = _path(data_dir)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append(data_dir, event: str, invoice: str | None, **data) -> dict:
    entries = read(data_dir)
    entry = {"seq": len(entries) + 1, "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "event": event, "invoice": invoice, "data": data,
             "prev_hash": entries[-1]["hash"] if entries else GENESIS}
    entry["hash"] = _hash(entry)
    with open(_path(data_dir), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def verify(data_dir) -> tuple[bool, int, str | None]:
    """(chain intact, number of entries, description of the first broken entry or None)."""
    entries, prev = read(data_dir), GENESIS
    for i, e in enumerate(entries, 1):
        if e.get("seq") != i or e.get("prev_hash") != prev:
            return False, len(entries), f"entry {i}: does not follow entry {i - 1}"
        if _hash(e) != e.get("hash"):
            return False, len(entries), f"entry {i} ({e.get('event')} {e.get('invoice')}): content changed"
        prev = e["hash"]
    return True, len(entries), None


def latest_hash(data_dir) -> str:
    entries = read(data_dir)
    return entries[-1]["hash"] if entries else GENESIS
