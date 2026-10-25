"""Tests for parser/invoice_parser.py + watcher integration.

Run: python3 parser/test_parser.py
Exit code 0 = all green.
"""

import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "watcher"))
from invoice_parser import ParseError, parse_invoice, parse_invoice_file  # noqa: E402
from inbox import InboxWatcher  # noqa: E402

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


def test_clean():
    inv = parse_invoice({
        "invoice_no": "INV-1042", "vendor": "Acme Office", "po": "PO-1042",
        "total": 4850,
        "lines": [{"sku": "PAPER-A4", "qty": 100, "unit_price": 48.50}],
    })
    assert inv.invoice_no == "INV-1042" and inv.vendor == "Acme Office"
    assert inv.po == "PO-1042" and inv.total == 4850
    assert inv.lines[0].line_total == 4850.0 and inv.warnings == []


def test_string_money_and_qty():
    inv = parse_invoice({
        "invoice_no": "INV-2091", "vendor": "Vertex Logistics",
        "po": "PO-2090", "total": "$7,800.00",
        "lines": [{"sku": "FREIGHT-MI", "qty": "60", "unit_price": "$130"}],
    })
    assert inv.total == 7800.0 and inv.lines[0].qty == 60
    assert inv.lines[0].unit_price == 130.0 and inv.warnings == []


def test_missing_total_computed():
    inv = parse_invoice({
        "invoice_no": "INV-1", "vendor": "V", "po": "PO-1",
        "lines": [{"sku": "A", "qty": 2, "unit_price": 10},
                  {"sku": "B", "qty": 3, "unit_price": 5}],
    })
    assert inv.total == 35.0
    assert any("computed from lines" in w for w in inv.warnings)


def test_total_mismatch_warns_not_fails():
    inv = parse_invoice({
        "invoice_no": "INV-2", "vendor": "V", "po": "PO-1", "total": 999,
        "lines": [{"sku": "A", "qty": 1, "unit_price": 10}],
    })
    assert inv.total == 999
    assert any("mismatch" in w for w in inv.warnings)


def test_aliases():
    inv = parse_invoice({
        "invoice_number": "INV-9", "supplier": "Nova",
        "po_number": "PO-9", "amount": 80,
        "items": [{"item": "RES-10K", "quantity": 1, "rate": 80}],
    })
    assert (inv.invoice_no, inv.vendor, inv.po, inv.total) == (
        "INV-9", "Nova", "PO-9", 80)


def test_unit_of_measure():
    inv = parse_invoice({
        "invoice_number": "INV-EV-208", "vendor": "Evergreen Parts Inc.",
        "po_number": "PO-7802", "total": 1500,
        "lines": [{"sku": "BR-6204", "qty": 10, "unit_price": 150, "uom": "box (12)"},
                  {"sku": "GR-500", "qty": 4, "unit_price": 0}],
    })
    assert inv.lines[0].unit == "box (12)"
    assert inv.lines[1].unit is None


def test_missing_invoice_no():
    try:
        parse_invoice({"vendor": "V", "lines": [
            {"sku": "A", "qty": 1, "unit_price": 1}]})
    except ParseError:
        return
    raise AssertionError("expected ParseError")


def test_missing_line_price():
    try:
        parse_invoice({"invoice_no": "X", "vendor": "V", "lines": [
            {"sku": "A", "qty": 1}]})
    except ParseError:
        return
    raise AssertionError("expected ParseError")


def test_missing_po_warns():
    inv = parse_invoice({
        "invoice_no": "INV-3", "vendor": "V", "total": 10,
        "lines": [{"sku": "A", "qty": 1, "unit_price": 10}],
    })
    assert inv.po is None
    assert any("no PO" in w for w in inv.warnings)


def test_file_roundtrip_and_bad_json():
    with tempfile.TemporaryDirectory() as d:
        good = os.path.join(d, "good.json")
        with open(good, "w") as f:
            json.dump({"invoice_no": "INV-5", "vendor": "V", "po": "PO-5",
                       "total": 20, "lines": [
                           {"sku": "A", "qty": 2, "unit_price": 10}]}, f)
        assert parse_invoice_file(good).invoice_no == "INV-5"
        bad = os.path.join(d, "bad.json")
        with open(bad, "w") as f:
            f.write("{not json")
        try:
            parse_invoice_file(bad)
        except ParseError:
            pass
        else:
            raise AssertionError("expected ParseError for bad JSON")


def test_watcher_integration():
    """Watcher drops -> parser parses; bad invoice -> error, watcher lives."""
    parsed, errors = [], []
    with tempfile.TemporaryDirectory() as d:
        watcher = InboxWatcher(
            d,
            on_invoice=lambda p, raw: parsed.append(parse_invoice(raw)),
            on_error=lambda p, e: errors.append(p.name),
            poll_interval=0.2)
        t = threading.Thread(target=watcher.run, daemon=True)
        t.start()
        try:
            time.sleep(0.5)
            with open(os.path.join(d, "ok.json"), "w") as f:
                json.dump({"invoice_no": "INV-7", "vendor": "V",
                           "po": "PO-7", "total": 30, "lines": [
                               {"sku": "A", "qty": 3, "unit_price": 10}]}, f)
            with open(os.path.join(d, "broken.json"), "w") as f:
                json.dump({"vendor": "V", "lines": [
                    {"sku": "A", "qty": 1, "unit_price": 1}]}, f)
            deadline = time.time() + 5
            while (len(parsed) + len(errors)) < 2 and time.time() < deadline:
                time.sleep(0.2)
            assert len(parsed) == 1 and parsed[0].invoice_no == "INV-7", parsed
            assert errors == ["broken.json"], errors
            # watcher still alive after the bad file: drop another good one
            with open(os.path.join(d, "ok2.json"), "w") as f:
                json.dump({"invoice_no": "INV-8", "vendor": "V",
                           "po": "PO-8", "total": 5, "lines": [
                               {"sku": "B", "qty": 1, "unit_price": 5}]}, f)
            deadline = time.time() + 5
            while len(parsed) < 2 and time.time() < deadline:
                time.sleep(0.2)
            assert len(parsed) == 2 and parsed[1].invoice_no == "INV-8", parsed
        finally:
            watcher.stop()
            t.join(timeout=2)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            check(name, fn)
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    sys.exit(1 if FAILED else 0)
