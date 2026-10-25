"""Invoice Watchdog — AP inbox watcher.

Watches a folder that acts as the AP inbox. When a new invoice file lands
(and is fully written), it is parsed and handed to the next stage via a
callback. Stdlib only — no pip installs needed on the venue machine.

Usage:
    python3 watcher/inbox.py --dir ./data/inbox
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path


class InboxWatcher:
    """Poll a folder for new invoice files and dispatch them once stable.

    A file is only processed after its size is unchanged across
    `stable_polls` consecutive polls, so partially written files are never
    parsed. Each file is processed exactly once. A file that fails to parse
    is retried only if its size or mtime changes afterwards, so a slow
    writer is tolerated without error spam — and for production drops,
    prefer the atomic convention: write `name.json.tmp`, then rename to
    `name.json` (the watcher only sees complete files).
    """

    def __init__(self, inbox_dir, on_invoice, on_error=None,
                 poll_interval=0.5, stable_polls=2,
                 extensions=(".json",)):
        self.inbox_dir = Path(inbox_dir)
        self.on_invoice = on_invoice
        self.on_error = on_error or (lambda p, e: print(
            f"[watcher] ERROR {p.name}: {e}", file=sys.stderr))
        self.poll_interval = poll_interval
        self.stable_polls = stable_polls
        self.extensions = tuple(e.lower() for e in extensions)
        self._stop = threading.Event()
        self._seen_sizes: dict[str, tuple[int, int]] = {}
        self._processed: set[str] = set()
        self._failed: dict[str, tuple[int, float]] = {}  # name -> (size, mtime)

    def stop(self):
        self._stop.set()

    def _candidates(self):
        if not self.inbox_dir.is_dir():
            return []
        out = []
        for p in sorted(self.inbox_dir.iterdir()):
            if not p.is_file():
                continue
            if p.name.startswith(".") or p.name.startswith("~"):
                continue
            if p.suffix.lower() not in self.extensions:
                continue
            if p.name in self._processed:
                continue
            out.append(p)
        return out

    def _poll_once(self):
        for path in self._candidates():
            try:
                st = path.stat()
            except FileNotFoundError:
                continue  # deleted between listing and stat
            size, mtime = st.st_size, st.st_mtime
            prev_size, stable = self._seen_sizes.get(path.name, (None, 0))
            stable = stable + 1 if prev_size == size else 0
            self._seen_sizes[path.name] = (size, stable)
            if stable < self.stable_polls:
                continue
            if self._failed.get(path.name) == (size, mtime):
                continue  # failed on identical content; wait for a change
            self._seen_sizes.pop(path.name, None)
            self._handle(path)

    def _handle(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                invoice = json.load(f)
        except Exception as exc:  # bad JSON must never kill the watcher
            try:
                st = path.stat()
                self._failed[path.name] = (st.st_size, st.st_mtime)
            except FileNotFoundError:
                pass
            self.on_error(path, exc)
            return
        self._failed.pop(path.name, None)
        try:
            self.on_invoice(path, invoice)
        except Exception as exc:
            self.on_error(path, exc)
            return
        self._processed.add(path.name)

    def run(self):
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        print(f"[watcher] Watching {self.inbox_dir.resolve()} "
              f"(poll {self.poll_interval}s) — Ctrl+C to stop")
        try:
            while not self._stop.is_set():
                self._poll_once()
                self._stop.wait(self.poll_interval)
        except KeyboardInterrupt:
            print("\n[watcher] Stopped.")


def main():
    ap = argparse.ArgumentParser(description="Invoice Watchdog inbox watcher")
    ap.add_argument("--dir", default="./data/inbox",
                    help="Inbox folder to watch")
    ap.add_argument("--interval", type=float, default=0.5,
                    help="Poll interval in seconds")
    args = ap.parse_args()

    def on_invoice(path, invoice):
        print(f"[watcher] NEW INVOICE {path.name}: "
              f"vendor={invoice.get('vendor')} total={invoice.get('total')}")

    InboxWatcher(args.dir, on_invoice, poll_interval=args.interval).run()


if __name__ == "__main__":
    main()
