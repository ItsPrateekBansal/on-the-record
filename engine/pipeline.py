"""Invoice Watchdog — the pipeline, end to end (steps 3-11 for each invoice in the inbox).

    python3 -m engine.pipeline --watch      # watch data/inbox/ and audit invoices as they arrive
    python3 -m engine.pipeline --once       # audit everything in data/inbox/ now, then stop
    Slack posts by default when SLACK_BOT_TOKEN + SLACK_CHANNEL are set
    (see docs/SLACK_SETUP.md); --no-slack turns it off.
    python3 -m engine.pipeline --selftest   # audit every demo invoice in a scratch copy of data/
                                            # and compare with data/expected_results.json

With a model (--model or $WATCHDOG_MODEL, e.g. the Nemotron or Qwen name from `ollama list`), the
model reads PDF invoices and the contract and rewrites explanations; Python validates all of it.
Without one, JSON invoices only, the rule-based contract reader and template explanations.
--selftest --model <name> runs the PDFs through the model too.
Each audited file moves from data/inbox/ to data/processed/.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import audit_log  # noqa: E402
from engine.checks import run_checks  # noqa: E402
from engine.evidence import DATA_DIR, EvidenceError, gather_evidence  # noqa: E402
from engine.llm import model_name  # noqa: E402
from engine.report import alert, explain_and_draft, save_transaction, write_result  # noqa: E402
from parser.invoice_parser import ParseError, parse_invoice, parse_invoice_file  # noqa: E402


def _read_invoice(path: Path, model: str | None):
    if path.suffix.lower() == ".pdf":
        if not model:
            raise ParseError(f"{path.name}: PDF needs --model (local model for extraction)")
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "parser"))
        from extract import extract_invoice, extract_text
        return parse_invoice(extract_invoice(extract_text(str(path)), model))
    return parse_invoice_file(path)


def _unreadable(path: Path, reason: str, data_dir: Path, vendor: str | None = None) -> dict:
    result = {"invoice": path.stem, "vendor": vendor, "vendor_key": None, "po": None, "date": None, "total": 0.0,
              "status": "NEEDS_REVIEW", "main_check": "missing_evidence", "at_risk": 0.0,
              "amount_under_review": 0.0, "layers": {}, "result_folder": "results/needs_review",
              "evidence": {}, "reasons": [reason], "calculation": [], "lines": [], "file": path.name}
    result["explanation"] = f"{path.name} could not be audited: {reason}"
    write_result(result, data_dir)
    audit_log.append(data_dir, "needs_review", path.stem, reason=reason)
    alert(result, data_dir)
    return result


def process_file(path, data_dir: Path = DATA_DIR, model: str | None = None, move: bool = True) -> dict:
    path, data_dir = Path(path), Path(data_dir)
    audit_log.append(data_dir, "received", None, file=path.name)
    try:
        invoice = _read_invoice(path, model)                                    # step 3
    except (ParseError, ValueError) as exc:
        return _unreadable(path, f"could not read the invoice ({exc})", data_dir)
    try:
        ev = gather_evidence(invoice, data_dir, model)                          # steps 4-6
    except EvidenceError as exc:
        return _unreadable(path, str(exc), data_dir, invoice.vendor)
    audit_log.append(data_dir, "evidence_loaded", invoice.invoice_no, company=ev.company.key, po=invoice.po,
                     previous=[p.invoice_no for p in ev.previous], problems=ev.problems, terms=ev.terms_source)

    result = run_checks(ev)                                                     # step 7
    result["file"] = path.name
    result["terms_source"] = ev.terms_source
    audit_log.append(data_dir, "checked", invoice.invoice_no, status=result["status"],
                     main_check=result["main_check"], at_risk=result["at_risk"])

    save_transaction(invoice, result, data_dir)                                 # step 8 (after step 6)
    index = json.loads((data_dir / "companies" / "index.json").read_text())
    result.update(explain_and_draft(result, index[result["vendor_key"]]["email"], model))  # step 10
    write_result(result, data_dir)                                              # step 9
    audit_log.append(data_dir, "reported", invoice.invoice_no, folder=result["result_folder"])
    text = alert(result, data_dir)                                              # step 11
    if text:
        audit_log.append(data_dir, "alerted", invoice.invoice_no, text=text)

    if move and path.parent == data_dir / "inbox":
        processed = data_dir / "processed"
        processed.mkdir(exist_ok=True)
        shutil.move(str(path), processed / path.name)
    return result


def _line(result: dict) -> str:
    money = f"${result['at_risk']:,.2f}" if result["status"] == "FAIL" else ""
    return f"{result['status']:<13} {result['invoice']:<12} {result.get('vendor') or '?':<28} {result['main_check'] or '':<17} {money}"


def run_once(data_dir: Path = DATA_DIR, model: str | None = None) -> list[dict]:
    inbox = Path(data_dir) / "inbox"
    files = sorted(p for p in inbox.iterdir() if p.suffix.lower() in (".json", ".pdf") and not p.name.startswith("."))
    results = []
    for p in files:
        results.append(process_file(p, data_dir, model))
        print(_line(results[-1]))
    return results


def _slack_flush(data_dir):
    """Best-effort: post queued alerts, never break the audit on Slack trouble."""
    from engine import slack
    try:
        posted, failed = slack.post_pending(data_dir)
    except slack.NotConfigured:
        return  # startup already warned once; stay silent per invoice
    except slack.SlackError as exc:
        print(f"[slack] post failed ({exc}); alerts stay queued")
    else:
        if posted or failed:
            print(f"[slack] posted {len(posted)} alert(s)"
                  + (f", {len(failed)} failed" if failed else ""))


def watch(data_dir: Path = DATA_DIR, model: str | None = None, slack: bool = False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "watcher"))
    from inbox import InboxWatcher
    exts = (".json", ".pdf") if model else (".json",)

    def on_invoice(path, _raw):
        print(_line(process_file(path, data_dir, model)))
        if slack:
            _slack_flush(data_dir)

    InboxWatcher(Path(data_dir) / "inbox", on_invoice, extensions=exts).run()


COMPARED = ("status", "main_check", "at_risk", "amount_under_review", "result_folder")


def selftest(data_dir: Path = DATA_DIR, model: str | None = None) -> bool:
    """Audit every demo invoice in a scratch copy of data/ and compare with the answer key."""
    expected = json.loads((Path(data_dir) / "expected_results.json").read_text())["invoices"]
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "data"
        shutil.copytree(data_dir, scratch, ignore=shutil.ignore_patterns("audit_log.jsonl", "alerts.jsonl"))
        for d in ("results", "processed", "outbox"):
            shutil.rmtree(scratch / d, ignore_errors=True)
        for row in expected:
            src = scratch / "demo" / row["set"] / (row["file"] if model else row["file"].replace(".pdf", ".json"))
            got = process_file(src, scratch, model, move=False)
            diffs = [k for k in COMPARED if got[k] != row[k]]
            diffs += [f"layers.{n}" for n in row["layers"] if got["layers"][n]["status"] != row["layers"][n]["status"]
                      or got["layers"][n]["checks"] != row["layers"][n]["checks"]]
            if got["layers"]["historical"]["matched_transaction"] != row["layers"]["historical"]["matched_transaction"]:
                diffs.append("matched_transaction")
            diffs += [f"evidence.{k}" for k in ("po", "receipt", "previous_transactions", "contract", "clauses")
                      if got["evidence"][k] != row["evidence"][k]]
            print(("ok   " if not diffs else "DIFF ") + _line(got) + (f"   {diffs}" if diffs else ""))
            bad += bool(diffs)
        ok, n, problem = audit_log.verify(scratch)
        print(f"\naudit log: {n} entries, chain {'intact' if ok else 'BROKEN: ' + problem}")
    print(f"{len(expected) - bad}/{len(expected)} invoices match the answer key")
    return bad == 0 and ok


def main():
    ap = argparse.ArgumentParser(description="Invoice Watchdog pipeline")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--watch", action="store_true", help="watch data/inbox/ and audit new invoices")
    mode.add_argument("--once", action="store_true", help="audit what is in data/inbox/ now")
    mode.add_argument("--selftest", action="store_true", help="compare every demo invoice with the answer key")
    ap.add_argument("--data", default=str(DATA_DIR), help="data folder (default: repo data/)")
    ap.add_argument("--model", help="local Ollama model (default: $WATCHDOG_MODEL). Without one: JSON "
                                    "invoices only, rule-based contract reading, template explanations")
    ap.add_argument("--slack", action="store_true",
                    help="accepted for compatibility; Slack posting is now always on "
                         "when configured (see docs/SLACK_SETUP.md)")
    ap.add_argument("--no-slack", action="store_true",
                    help="do not post to Slack even when configured")
    args = ap.parse_args()
    data_dir, model = Path(args.data), model_name(args.model)
    if args.selftest:
        sys.exit(0 if selftest(data_dir, model) else 1)
    slack_on = not args.no_slack
    if slack_on:
        from engine import slack
        try:
            slack.config()
        except slack.NotConfigured as exc:
            print(f"[slack] disabled: {exc}")
            slack_on = False
    print(f"model: {model or 'none (rules + templates)'}")
    if args.once:
        run_once(data_dir, model)
        if slack_on:
            _slack_flush(data_dir)
    else:
        watch(data_dir, model, slack=slack_on)


if __name__ == "__main__":
    main()
