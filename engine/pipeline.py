"""Invoice Watchdog — the pipeline, end to end (steps 3-11 for each invoice in the inbox).

    python3 -m engine.pipeline --watch      # watch data/inbox/ and audit invoices as they arrive
    python3 -m engine.pipeline --once       # audit everything in data/inbox/ now, then stop
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
from engine.evidence import DATA_DIR, EvidenceError, check_contracts, gather_evidence  # noqa: E402
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


def process_file(path, data_dir: Path = DATA_DIR, model: str | None = None, move: bool = True,
                 fallback: bool = True) -> dict:
    path, data_dir = Path(path), Path(data_dir)
    audit_log.append(data_dir, "received", None, file=path.name)
    try:
        invoice = _read_invoice(path, model)                                    # step 3
    except (ParseError, ValueError) as exc:
        return _unreadable(path, f"could not read the invoice ({exc})", data_dir)
    try:
        ev = gather_evidence(invoice, data_dir, model, fallback)                # steps 4-6
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


def preflight(data_dir: Path, model: str | None, fallback: bool):
    """With a model: read all contracts now, so no invoice waits for it and problems show up early."""
    if model:
        print(f"reading contracts with {model} ...")
        for line in check_contracts(model, data_dir, fallback):
            print("  " + line)


def run_once(data_dir: Path = DATA_DIR, model: str | None = None, fallback: bool = True) -> list[dict]:
    inbox = Path(data_dir) / "inbox"
    files = sorted(p for p in inbox.iterdir() if p.suffix.lower() in (".json", ".pdf") and not p.name.startswith("."))
    results = []
    for p in files:
        results.append(process_file(p, data_dir, model, fallback=fallback))
        print(_line(results[-1]))
    return results


def watch(data_dir: Path = DATA_DIR, model: str | None = None, fallback: bool = True):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "watcher"))
    from inbox import InboxWatcher
    exts = (".json", ".pdf") if model else (".json",)
    InboxWatcher(Path(data_dir) / "inbox",
                 lambda path, _raw: print(_line(process_file(path, data_dir, model, fallback=fallback))),
                 extensions=exts).run()


COMPARED = ("status", "main_check", "at_risk", "amount_under_review", "result_folder")


def selftest(data_dir: Path = DATA_DIR, model: str | None = None, fallback: bool = True) -> bool:
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
            got = process_file(src, scratch, model, move=False, fallback=fallback)
            diffs = [k for k in COMPARED if got[k] != row[k]]
            if not got["layers"]:                       # could not be read: reasons say why
                diffs.append(f"unreadable: {got['reasons'][0][:120]}")
            else:
                diffs += [f"layers.{n}" for n in row["layers"]
                          if got["layers"][n]["status"] != row["layers"][n]["status"]
                          or got["layers"][n]["checks"] != row["layers"][n]["checks"]]
                if got["layers"]["historical"]["matched_transaction"] != row["layers"]["historical"]["matched_transaction"]:
                    diffs.append("matched_transaction")
                diffs += [f"evidence.{k}" for k in ("po", "receipt", "previous_transactions", "contract", "clauses")
                          if got["evidence"].get(k) != row["evidence"][k]]
            via = f"   [{got['terms_source']}]" if model and "rules" in got.get("terms_source", "") else ""
            print(("ok   " if not diffs else "DIFF ") + _line(got) + (f"   {diffs}" if diffs else "") + via)
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
    ap.add_argument("--no-fallback", action="store_true",
                    help="strict: contract terms the model still gets wrong go to NEEDS_REVIEW "
                         "(default: the rule-based reader is used for them, marked in terms_source)")
    args = ap.parse_args()
    data_dir, model, fallback = Path(args.data), model_name(args.model), not args.no_fallback
    if args.selftest:
        sys.exit(0 if selftest(data_dir, model, fallback) else 1)
    print(f"model: {model or 'none (rules + templates)'}")
    preflight(data_dir, model, fallback)
    if args.once:
        run_once(data_dir, model, fallback)
    else:
        watch(data_dir, model, fallback)


if __name__ == "__main__":
    main()
