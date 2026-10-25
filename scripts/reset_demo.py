"""Reset data/ to the state before a demo run.

Run:  python3 scripts/reset_demo.py

Empties inbox/, processed/, results/ and outbox/, deletes the audit log and alerts, and removes
transactions the pipeline added (the original previous transactions, which have "paid_on", stay).
Stdlib only, so it works on the GB10 without reportlab (unlike make_fake_data.py).
"""
import json
import shutil
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def main():
    for d in ["inbox", "processed", "outbox", "results/success", "results/discrepancy", "results/needs_review"]:
        folder = DATA / d
        if folder.exists():
            for p in folder.iterdir():
                if p.name != ".gitkeep":
                    shutil.rmtree(p) if p.is_dir() else p.unlink()
    for f in ["audit_log.jsonl", "alerts.jsonl"]:
        (DATA / f).unlink(missing_ok=True)
    removed = 0
    for tx in (DATA / "companies").glob("*/transactions/*.json"):
        if "paid_on" not in json.loads(tx.read_text()):
            tx.unlink()
            removed += 1
    print(f"reset: inbox, processed, results, outbox, logs cleared; {removed} audited transactions removed")


if __name__ == "__main__":
    main()
