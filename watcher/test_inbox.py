"""Test for watcher/inbox.py — run: python3 watcher/test_inbox.py

Covers: complete file detected, slow/partial write processed exactly once
with full content, non-JSON file ignored, invalid JSON reported without
killing the watcher, watcher still alive afterwards.
"""

import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inbox import InboxWatcher  # noqa: E402


def main():
    received = []
    errors = []
    with tempfile.TemporaryDirectory() as tmp:
        w = InboxWatcher(tmp,
                         lambda p, inv: received.append((p, inv)),
                         lambda p, e: errors.append((p, e)),
                         poll_interval=0.2, stable_polls=2)
        t = threading.Thread(target=w.run, daemon=True)
        t.start()
        try:
            # 1. complete file
            p1 = os.path.join(tmp, "inv-001.json")
            with open(p1, "w") as f:
                json.dump({"vendor": "Acme", "total": 1200}, f)

            # 2. slow write: two chunks with a gap (must arrive once, complete)
            p2 = os.path.join(tmp, "inv-002.json")
            with open(p2, "w") as f:
                f.write('{"vendor": "Vertex", "total": ')
                f.flush()
                time.sleep(0.7)
                f.write("850}")

            # 3. ignored: wrong extension
            with open(os.path.join(tmp, "notes.txt"), "w") as f:
                f.write("not an invoice")

            # 4. invalid JSON: error reported, watcher survives
            with open(os.path.join(tmp, "bad.json"), "w") as f:
                f.write("{not json")

            # 5. valid file after the bad one (proves survival)
            p3 = os.path.join(tmp, "inv-003.json")
            with open(p3, "w") as f:
                json.dump({"vendor": "Nova", "total": 430}, f)

            # 6. PDF passthrough: handed to the callback untouched (the
            # pipeline extracts it with the local model); needs extensions
            # enabled, so it is covered by the second watcher below.
            deadline = time.time() + 5
            while len(received) < 3 and time.time() < deadline:
                time.sleep(0.1)
        finally:
            w.stop()
            t.join(timeout=2)

    names = sorted(p.name for p, _ in received)
    assert names == ["inv-001.json", "inv-002.json", "inv-003.json"], names
    by_name = {p.name: inv for p, inv in received}
    assert by_name["inv-002.json"] == {"vendor": "Vertex", "total": 850}, \
        by_name["inv-002.json"]  # slow write arrived whole, once
    bad_errors = [p for p, _ in errors if p.name == "bad.json"]
    assert len(bad_errors) == 1, errors  # unchanging bad file: one error, no spam
    print("PASS: 3 invoices received, slow write whole + once, "
          "txt ignored, bad JSON reported once, watcher survived.")
    print("Received:", [(p.name, inv) for p, inv in received])

    # PDF passthrough, with .pdf in extensions.
    pdf_received = []
    with tempfile.TemporaryDirectory() as tmp:
        w = InboxWatcher(tmp,
                         lambda p, inv: pdf_received.append((p, inv)),
                         poll_interval=0.2, stable_polls=2,
                         extensions=(".json", ".pdf"))
        t = threading.Thread(target=w.run, daemon=True)
        t.start()
        try:
            with open(os.path.join(tmp, "inv.pdf"), "wb") as f:
                f.write(b"%PDF-1.4 fake")
            deadline = time.time() + 5
            while not pdf_received and time.time() < deadline:
                time.sleep(0.1)
        finally:
            w.stop()
            t.join(timeout=2)
    assert len(pdf_received) == 1 and pdf_received[0][0].name == "inv.pdf" \
        and pdf_received[0][1] is None, pdf_received
    print("PASS: PDF passed through untouched (callback payload None).")


if __name__ == "__main__":
    main()
