"""Tests for the checks, reporting, audit log and approval (pipeline steps 7-13).

Run: python3 engine/test_pipeline.py
Exit code 0 = all green. Every test works on a scratch copy of data/.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from engine import audit_log  # noqa: E402
from engine.approval import ApprovalError, approve_dispute, mark_correct  # noqa: E402
from engine.evidence import DATA_DIR  # noqa: E402
from engine.pipeline import process_file, selftest  # noqa: E402

PASSED = []
FAILED = []


def check(name, fn):
    try:
        fn()
    except Exception as exc:
        FAILED.append((name, exc))
        print(f"FAIL {name}: {exc}")
    else:
        PASSED.append(name)
        print(f"PASS {name}")


def scratch():
    tmp = Path(tempfile.mkdtemp()) / "data"
    shutil.copytree(DATA_DIR, tmp, ignore=shutil.ignore_patterns("audit_log.jsonl", "alerts.jsonl"))
    for d in ("results", "processed", "outbox", "inbox"):
        shutil.rmtree(tmp / d, ignore_errors=True)
        (tmp / d).mkdir()
    for f in ("success", "discrepancy", "needs_review"):
        (tmp / "results" / f).mkdir()
    for tx in tmp.glob("companies/*/transactions/*.json"):      # only the original history
        if "paid_on" not in json.loads(tx.read_text()):
            tx.unlink()
    return tmp


def drop(data, demo_file, body=None):
    path = data / "inbox" / Path(demo_file).name
    if body is None:
        shutil.copyfile(data / "demo" / demo_file, path)
    else:
        path.write_text(body if isinstance(body, str) else json.dumps(body))
    return process_file(path, data)


def test_selftest_all_demo_invoices():
    assert selftest(DATA_DIR)


def test_bolt_po_passes_contract_fails():
    r = drop(scratch(), "live/01_bolt_INV-B-5520.json")
    assert (r["status"], r["at_risk"], r["main_check"]) == ("FAIL", 720.0, "contract_price")
    assert r["layers"]["transaction"]["status"] == "PASS"
    assert "3.1" in r["evidence"]["clauses"] and "$12.00" in r["dispute_draft"]


def test_files_land_in_the_right_places():
    data = scratch()
    r = drop(data, "live/01_bolt_INV-B-5520.json")
    assert (data / "results" / "discrepancy" / "INV-B-5520.json").exists()
    assert (data / "processed" / "01_bolt_INV-B-5520.json").exists()
    assert not (data / "inbox" / "01_bolt_INV-B-5520.json").exists()
    saved = json.loads((data / "companies" / "bolt" / "transactions" / "INV-B-5520.json").read_text())
    assert saved["status"] == "FAIL"
    alerts = (data / "alerts.jsonl").read_text()
    assert "$720.00" in alerts and "12.00" not in alerts and "3.1" not in alerts   # no prices or clauses in Slack


def test_reaudit_is_not_a_self_duplicate():
    data = scratch()
    first = drop(data, "live/04_delta_INV-D-3301.json")
    again = drop(data, "live/04_delta_INV-D-3301.json")
    assert first["status"] == again["status"] == "PASS"
    assert again["layers"]["historical"]["matched_transaction"] is None


def test_disputed_invoice_does_not_count_as_billed():
    data = scratch()
    drop(data, "live/01_bolt_INV-B-5520.json")                 # FAIL, saved to transactions
    fixed = json.loads((data / "demo" / "live" / "01_bolt_INV-B-5520.json").read_text())
    fixed.update(invoice_number="INV-B-5520R", total=6000.0)
    fixed["lines"][0]["unit_price"] = 12.0
    r = drop(data, "x.json", fixed)                            # corrected re-issue on the same PO
    assert r["layers"]["transaction"]["checks"]["po_quantity"] == "PASS", r["calculation"]
    assert r["layers"]["historical"]["checks"]["duplicate"] == "PASS"


def test_carton_needs_review():
    r = drop(scratch(), "overnight/o04_evergreen_INV-EV-199.json")
    assert (r["status"], r["main_check"], r["at_risk"], r["amount_under_review"]) == \
        ("NEEDS_REVIEW", "unit_of_measure", 0.0, 374.4)
    assert r["dispute_draft"] is None and "carton" in r["reasons"][0]


def test_unknown_po_and_bad_json_need_review():
    data = scratch()
    r = drop(data, "x.json", {"invoice_number": "INV-Z", "vendor": "Bolt Industrial Supply LLC", "po_number": "PO-0000",
                              "total": 12, "lines": [{"sku": "BX-200", "qty": 1, "unit_price": 12}]})
    assert r["status"] == "NEEDS_REVIEW" and any("PO-0000 not found" in x for x in r["reasons"])
    bad = drop(data, "bad.json", "{not json")
    assert bad["status"] == "NEEDS_REVIEW" and (data / "results" / "needs_review" / "bad.json").exists()
    who = drop(data, "who.json", {"invoice_number": "INV-Q", "vendor": "Nobody Ltd", "total": 1,
                                  "lines": [{"sku": "A", "qty": 1, "unit_price": 1}]})
    assert who["status"] == "NEEDS_REVIEW" and "Nobody" in who["reasons"][0]


def test_approval_writes_outbox_only_for_failures():
    data = scratch()
    drop(data, "live/01_bolt_INV-B-5520.json")
    drop(data, "live/04_delta_INV-D-3301.json")
    path = approve_dispute("INV-B-5520", "Ananya", data)
    assert path.read_text().startswith("STATUS: READY TO SEND (approved by Ananya")
    for bad in (lambda: approve_dispute("INV-D-3301", "Ananya", data),       # clean: nothing to dispute
                lambda: approve_dispute("INV-B-5520", "Ananya", data),       # twice
                lambda: approve_dispute("INV-NOPE", "Ananya", data)):
        try:
            bad()
        except ApprovalError:
            continue
        raise AssertionError("expected ApprovalError")
    assert [p.name for p in (data / "outbox").iterdir()] == ["INV-B-5520_dispute.txt"]


def test_mark_correct_moves_to_success_and_counts():
    data = scratch()
    drop(data, "overnight/o04_evergreen_INV-EV-199.json")
    mark_correct("INV-EV-199", "Ananya", data)
    assert (data / "results" / "success" / "INV-EV-199.json").exists()
    assert not (data / "results" / "needs_review" / "INV-EV-199.json").exists()
    tx = json.loads((data / "companies" / "evergreen" / "transactions" / "INV-EV-199.json").read_text())
    assert tx["status"] == "PASS"


def test_audit_log_detects_tampering():
    data = scratch()
    drop(data, "live/01_bolt_INV-B-5520.json")
    approve_dispute("INV-B-5520", "Ananya", data)
    ok, n, _ = audit_log.verify(data)
    assert ok and n >= 6
    lines = (data / "audit_log.jsonl").read_text().splitlines()
    entry = json.loads(lines[2])
    entry["data"]["at_risk"] = 0
    lines[2] = json.dumps(entry)
    (data / "audit_log.jsonl").write_text("\n".join(lines) + "\n")
    ok, _, problem = audit_log.verify(data)
    assert not ok and "entry 3" in problem


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            check(name, fn)
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    sys.exit(1 if FAILED else 0)
