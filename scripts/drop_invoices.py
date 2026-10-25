"""Simulate invoices arriving in the AP inbox: copy demo invoices into data/inbox/, one at a time.

Run:  python3 scripts/drop_invoices.py data/demo/live
      python3 scripts/drop_invoices.py data/demo/overnight --delay 0.5
      python3 scripts/drop_invoices.py data/demo/live --pdf      # PDFs, once PDF extraction works

Each file is written as <name>.tmp and then renamed, so the watcher never sees a half-written file.
"""
import argparse
import shutil
import time
from pathlib import Path

INBOX = Path(__file__).resolve().parent.parent / "data" / "inbox"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="folder of demo invoices, e.g. data/demo/live")
    ap.add_argument("--pdf", action="store_true", help="drop the PDFs instead of the JSON twins")
    ap.add_argument("--delay", type=float, default=3.0, help="seconds between invoices (for a live demo feel)")
    args = ap.parse_args()

    files = sorted(Path(args.folder).glob("*.pdf" if args.pdf else "*.json"))
    if not files:
        raise SystemExit(f"No invoices in {args.folder}")
    INBOX.mkdir(parents=True, exist_ok=True)
    for i, src in enumerate(files):
        tmp = INBOX / (src.name + ".tmp")
        shutil.copyfile(src, tmp)
        tmp.rename(INBOX / src.name)
        print(f"arrived: {src.name}")
        if i < len(files) - 1:
            time.sleep(args.delay)


if __name__ == "__main__":
    main()
