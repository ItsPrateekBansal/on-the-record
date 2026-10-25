"""Tests for engine/evidence.py against the demo data in data/.

Run: python3 engine/test_evidence.py
Exit code 0 = all green.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from engine.evidence import (DATA_DIR, EvidenceError, extract_terms, gather_evidence,  # noqa: E402
                             load_company, load_transactions, read_contract)
from parser.invoice_parser import parse_invoice, parse_invoice_file  # noqa: E402

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


def test_load_company_names():
    assert load_company("Bolt Industrial Supply LLC").key == "bolt"
    assert load_company("bolt industrial").key == "bolt"
    assert load_company("EVERGREEN PARTS, INC.").key == "evergreen"


def test_unknown_vendor_raises():
    try:
        load_company("Nobody Supplies")
    except EvidenceError:
        return
    raise AssertionError("expected EvidenceError")


def test_read_contract_clauses_word_for_word():
    c = read_contract(load_company("Bolt Industrial Supply LLC"))
    assert c.clauses["3.1"] == "Unit price for SKU BX-200 shall be $12.00 per unit, fixed through Dec 31, 2026."
    assert list(c.sections) == ["1", "2", "3", "4", "5"]
    assert (c.effective_from, c.effective_to) == ("2026-01-01", "2026-12-31")


def test_terms_bolt_tier():
    co = load_company("Bolt Industrial Supply LLC")
    t = extract_terms(read_contract(co), co)["BX-200"]
    assert (t.unit_price, t.clause, t.volume_tier) == (12.00, "3.1", (2000, 11.40, "3.2"))


def test_terms_evergreen_box_and_tube():
    co = load_company("Evergreen Parts Inc.")
    terms = extract_terms(read_contract(co), co)
    assert (terms["BR-6204"].unit_price, terms["BR-6204"].units_per_box) == (11.50, 12)
    assert (terms["GR-500"].unit_price, terms["GR-500"].unit, terms["GR-500"].units_per_box) == (7.80, "tube", None)


def test_terms_coastal_price_in_words():
    co = load_company("Coastal Supply Co.")
    assert extract_terms(read_contract(co), co)["CS-PAL"].unit_price == 60.00


def test_every_contract_price_found():
    index = json.loads((DATA_DIR / "companies" / "index.json").read_text())
    for c in index.values():
        co = load_company(c["name"])
        for sku, t in extract_terms(read_contract(co), co).items():
            assert t.unit_price is not None, f"{c['name']} {sku}"
            assert t.quote, f"{c['name']} {sku}: empty quote"


def test_evidence_matches_answer_key():
    """PO, receipt and previous transactions for every demo invoice agree with expected_results.json."""
    expected = json.loads((DATA_DIR / "expected_results.json").read_text())["invoices"]
    for row in expected:
        inv = parse_invoice_file(DATA_DIR / "demo" / row["set"] / row["file"].replace(".pdf", ".json"))
        ev = gather_evidence(inv)
        want = row["evidence"]
        got_po = f"companies/{ev.company.key}/pos/{ev.po['po_number']}.json"
        got_gr = f"companies/{ev.company.key}/receipts/{ev.receipt['receipt_id']}.json"
        got_prev = [f"companies/{ev.company.key}/transactions/{p.invoice_no}.json" for p in ev.previous]
        assert (got_po, got_gr, got_prev) == (want["po"], want["receipt"], want["previous_transactions"]), row["invoice"]
        assert ev.problems == [], (row["invoice"], ev.problems)


def test_acme_history_found():
    ev = gather_evidence(parse_invoice_file(DATA_DIR / "demo" / "live" / "03_acme_INV-1047.json"))
    assert [p.invoice_no for p in ev.previous] == ["INV-1043"]
    assert ev.previous[0].lines[0].qty == 1200


def test_invoice_never_matches_itself():
    co = load_company("Delta Office Solutions")
    assert [p.invoice_no for p in load_transactions(co, "PO-7695")] == ["INV-D-3270"]
    assert load_transactions(co, "PO-7695", exclude_invoice="INV-D-3270") == []


def test_missing_po_is_a_problem_not_a_crash():
    inv = parse_invoice({"invoice_no": "INV-X", "vendor": "Bolt Industrial Supply LLC", "po": "PO-0000",
                         "total": 12, "lines": [{"sku": "ZZ-999", "qty": 1, "unit_price": 12}]})
    ev = gather_evidence(inv)
    assert ev.po is None and ev.receipt is None
    assert any("PO-0000 not found" in p for p in ev.problems)
    assert any("ZZ-999: not in" in p for p in ev.problems)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            check(name, fn)
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    sys.exit(1 if FAILED else 0)
