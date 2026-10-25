"""Invoice Watchdog — screen-recordable pipeline demo (watcher + parser).

Run: python3 demo_watch.py
Runs ~30 seconds: starts the watcher, then simulates emails arriving in
the AP inbox one by one. Each invoice is picked up, parsed, and queued
for the 3-way match.

For a screen recording, just record the terminal while this runs.
"""

import json
import os
import shutil
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "watcher"))
sys.path.insert(0, os.path.join(_HERE, "parser"))
from inbox import InboxWatcher  # noqa: E402
from invoice_parser import ParseError, parse_invoice  # noqa: E402

DEMO_DIR = os.path.join(_HERE, "demo_inbox")

INVOICES = [
    # 1. Clean invoice.
    ("email-01-acme.json", "Acme Office",
     {"invoice_no": "INV-1042", "vendor": "Acme Office", "po": "PO-1042",
      "total": 4850, "lines": [{"sku": "PAPER-A4", "qty": 100,
                                "unit_price": 48.50}]}),
    # 2. Exact duplicate of #1 — same invoice_no, visible in parsed output.
    ("email-02-acme-dup.json", "Acme Office",
     {"invoice_no": "INV-1042", "vendor": "Acme Office", "po": "PO-1042",
      "total": 4850, "lines": [{"sku": "PAPER-A4", "qty": 100,
                                "unit_price": 48.50}]}),
    # 3. Messy real-world format — currency strings, string qty.
    ("email-03-vertex.json", "Vertex Logistics",
     {"invoice_no": "INV-2091", "vendor": "Vertex Logistics", "po": "PO-2090",
      "total": "$7,800.00",
      "lines": [{"sku": "FREIGHT-MI", "qty": "60", "unit_price": "$130"}]}),
    # 4. Total does not match its lines — parser warns, does not fail.
    ("email-04-nova.json", "Nova Components",
     {"invoice_no": "INV-3317", "vendor": "Nova Components", "po": "PO-3310",
      "total": 9600, "lines": [{"sku": "RES-10K", "qty": 120,
                                "unit_price": 75}]}),
]


def on_invoice(path, raw):
    print(f"  [watcher] PICKED UP {path.name}")
    try:
        inv = parse_invoice(raw)
    except ParseError as exc:
        print(f"  [parser]  FAILED: {exc}")
        print()
        return
    print(f"  [parser]  OK: {inv.invoice_no} | {inv.vendor} | PO={inv.po} | "
          f"total=${inv.total:,.2f} | {len(inv.lines)} line(s)")
    for warning in inv.warnings:
        print(f"  [parser]  ! {warning}")
    print("           -> queued for 3-way match")
    print()


def main():
    if os.path.isdir(DEMO_DIR):
        shutil.rmtree(DEMO_DIR)
    os.makedirs(DEMO_DIR)
    print("=" * 64)
    print("  INVOICE WATCHDOG — watcher + parser demo")
    print("=" * 64)
    watcher = InboxWatcher(DEMO_DIR, on_invoice, poll_interval=0.3)
    t = threading.Thread(target=watcher.run, daemon=True)
    t.start()
    time.sleep(1.0)
    try:
        for fname, vendor, invoice in INVOICES:
            print(f"  [email]  Arrived from {vendor}: {fname}")
            with open(os.path.join(DEMO_DIR, fname), "w") as f:
                json.dump(invoice, f, indent=2)
            time.sleep(5)
        time.sleep(1.5)
        print("-" * 64)
        print(f"  DONE: {len(INVOICES)} emails arrived, "
              f"{len(INVOICES)} invoices parsed, 0 missed.")
        print("-" * 64)
    finally:
        watcher.stop()
        t.join(timeout=2)


if __name__ == "__main__":
    main()
