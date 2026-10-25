"""Invoice Watchdog — one-command demo run.

    python3 demo.py [--delay 1.5] [--model <ollama name>] [--pdf]

Resets the demo state, starts the always-on agent (the inbox watcher +
pipeline) in a thread, then places invoices into data/inbox/ the way
emails would arrive: the overnight batch first (morning summary), then
the live batch one by one, then the wifi-off invoice. Prints every
verdict, every alert, the morning summary and the final totals, and
verifies the audit chain at the end.

JSON invoices by default: works with no model at all. --pdf drops the
PDF twins instead and needs --model (a local Ollama model for
extraction) or $WATCHDOG_MODEL. The watcher only ever sees complete
files: each drop is written as <name>.tmp and renamed, exactly like
scripts/drop_invoices.py.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "watcher"))
from engine import alerts, audit_log  # noqa: E402
from engine.llm import model_name  # noqa: E402
from engine.pipeline import process_file  # noqa: E402
from inbox import InboxWatcher  # noqa: E402

DATA = ROOT / "data"
PHASES = [
    ("overnight", DATA / "demo" / "overnight", "morning summary"),
    ("live", DATA / "demo" / "live", "live catches"),
    ("wifi_off", DATA / "demo" / "wifi_off", "wifi-off catch"),
]


def _line(result: dict) -> str:
    money = f" ${result['at_risk']:,.2f}" if result["status"] == "FAIL" else ""
    return (f"{result['status']:<13} {result['invoice']:<12} "
            f"{result.get('vendor') or '?':<28} "
            f"{result['main_check'] or '':<17}{money}")


def _phase_totals(results: list[dict]) -> str:
    fails = [r for r in results if r["status"] == "FAIL"]
    review = [r for r in results if r["status"] == "NEEDS_REVIEW"]
    text = (f"{len(results)} audited, {len(fails)} failed, "
            f"${sum(r['at_risk'] for r in fails):,.2f} at risk")
    if review:
        text += f", {len(review)} need review"
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description="Invoice Watchdog one-command demo")
    ap.add_argument("--delay", type=float, default=1.5,
                    help="seconds between invoices (default 1.5)")
    ap.add_argument("--model", help="local Ollama model (default: $WATCHDOG_MODEL)")
    ap.add_argument("--pdf", action="store_true",
                    help="drop the PDF twins instead of JSON (needs --model)")
    ap.add_argument("--data", default=str(DATA), help="data folder")
    args = ap.parse_args()
    data_dir, model = Path(args.data), model_name(args.model)
    if args.pdf and not model:
        print("error: --pdf needs --model (PDF extraction runs on the local model)")
        return 2
    exts = (".json", ".pdf") if model else (".json",)
    suffix = ".pdf" if args.pdf else ".json"

    print("== reset ==")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "reset_demo.py")],
                   check=True)
    inbox = data_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    lock = threading.Lock()

    def on_invoice(path, _raw):
        result = process_file(path, data_dir, model)
        with lock:
            results.append(result)
        print("  " + _line(result))

    watcher = InboxWatcher(inbox, on_invoice, poll_interval=0.3, extensions=exts)
    thread = threading.Thread(target=watcher.run, daemon=True)
    thread.start()
    try:
        for name, folder, label in PHASES:
            files = sorted(folder.glob(f"*{suffix}"))
            if not files:
                print(f"-- {name}: no {suffix} invoices in {folder}, skipped")
                continue
            print(f"\n== {name}: {label} ({len(files)} invoices) ==")
            before = len(results)
            for i, src in enumerate(files):
                tmp = inbox / (src.name + ".tmp")
                shutil.copyfile(src, tmp)
                tmp.rename(inbox / src.name)
                print(f"  arrived: {src.name}")
                if i < len(files) - 1:
                    time.sleep(args.delay)
            deadline = time.time() + 60
            while len(results) < before + len(files) and time.time() < deadline:
                time.sleep(0.1)
            phase = results[before:]
            print(f"-- {name}: {_phase_totals(phase)}")
            if name == "overnight":
                print("\n-- morning summary --")
                print("  " + alerts.summary(data_dir))
    finally:
        watcher.stop()
        thread.join(timeout=3)

    print("\n== final ==")
    print(f"  week: {_phase_totals(results)}")
    for folder in ("success", "discrepancy", "needs_review"):
        path = data_dir / "results" / folder
        n = len(list(path.glob("*.json"))) if path.exists() else 0
        print(f"  results/{folder}: {n} reports")
    ok, n, problem = audit_log.verify(data_dir)
    print(f"  audit log: {n} entries, "
          f"{'chain intact' if ok else 'CHAIN BROKEN: ' + problem}")
    print("\nDashboard: streamlit run dashboard/app.py")
    print("Approve a dispute there to move it to data/outbox/ (ready to send).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
