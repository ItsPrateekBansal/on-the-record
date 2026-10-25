"""Tests for engine/evidence.py against the demo data in data/.

Run: python3 engine/test_evidence.py
Exit code 0 = all green.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from engine.evidence import (DATA_DIR, EvidenceError, _validated_term, extract_terms,  # noqa: E402
                             gather_evidence, load_company, load_transactions, read_contract)
from engine import evidence  # noqa: E402
from engine import llm  # noqa: E402
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
    assert "INV-D-3270" in [p.invoice_no for p in load_transactions(co, "PO-7695")]
    assert "INV-D-3270" not in [p.invoice_no for p in load_transactions(co, "PO-7695", exclude_invoice="INV-D-3270")]


def test_missing_po_is_a_problem_not_a_crash():
    inv = parse_invoice({"invoice_no": "INV-X", "vendor": "Bolt Industrial Supply LLC", "po": "PO-0000",
                         "total": 12, "lines": [{"sku": "ZZ-999", "qty": 1, "unit_price": 12}]})
    ev = gather_evidence(inv)
    assert ev.po is None and ev.receipt is None
    assert any("PO-0000 not found" in p for p in ev.problems)
    assert any("ZZ-999: not in" in p for p in ev.problems)



def test_model_terms_are_checked_against_the_contract():
    c = read_contract(load_company("Bolt Industrial Supply LLC"))
    good = {"clause": "3.1", "quote": "Unit price for SKU BX-200 shall be $12.00 per unit", "unit_price": 12.0,
            "unit": "unit", "units_per_box": None,
            "volume_tier": {"more_than_qty": 2000, "unit_price": 11.40, "clause": "3.2"}}
    term, why = _validated_term("BX-200", good, c)
    assert why is None and term.volume_tier == (2000, 11.40, "3.2") and term.quote == c.clauses["3.1"]
    for change, expect in [({"unit_price": 13.44}, "not written"), ({"clause": "3.9"}, "does not exist"),
                           ({"quote": "Unit price for SKU BX-200 shall be $13.44"}, "quote"),
                           ({"units_per_box": 24}, "per box"),
                           ({"volume_tier": {"more_than_qty": 500, "unit_price": 11.40, "clause": "3.2"}}, "tier")]:
        term, why = _validated_term("BX-200", good | change, c)
        assert term is None and expect in why, (change, why)
    delta = read_contract(load_company("Delta Office Solutions"))
    pens = {"clause": "2.3", "quote": "Ballpoint pens (SKU DO-PEN) are $9.50 per box of 50.", "unit_price": 9.5,
            "unit": "box of 50", "units_per_box": 50, "volume_tier": None}
    term, why = _validated_term("DO-PEN", pens, delta, "box")       # priced per box: no conversion
    assert why is None and (term.unit, term.units_per_box) == ("box", None)



# ---- the model path, with a fake model (no Ollama needed)
DELTA_OK = [
    {"sku": "DO-PPR", "clause": "2.1", "unit": "case", "unit_price": 45.0, "units_per_box": None, "volume_tier": None,
     "quote": "Copy paper (SKU DO-PPR) is $45.00 per case of ten reams."},
    {"sku": "DO-TNR", "clause": "2.2", "unit": "unit", "unit_price": 85.0, "units_per_box": None, "volume_tier": None,
     "quote": "Black high-yield toner cartridges (SKU DO-TNR) are $85.00 each."},
    {"sku": "DO-PEN", "clause": "2.3", "unit": "box", "unit_price": 9.5, "units_per_box": 50, "volume_tier": None,
     "quote": "Ballpoint pens (SKU DO-PEN) are $9.50 per box of 50."},
]


class FakeModel:
    """Plays back answers in order (the last one repeats) and records the prompts."""
    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def __call__(self, prompt, model, timeout=180):
        self.prompts.append(prompt)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return {"terms": answer}


def with_fake(fake, fn):
    real = llm.generate_json
    llm.generate_json = fake
    evidence._TERMS_CACHE.clear()
    try:
        return fn()
    finally:
        llm.generate_json = real
        evidence._TERMS_CACHE.clear()


def delta():
    co = load_company("Delta Office Solutions")
    return read_contract(co), co


def test_model_formatting_differences_are_accepted():
    messy = [dict(DELTA_OK[0], sku="DO-PPR (Copy paper)", clause="Clause 2.1", unit_price="$45.00",
                  quote="\u201cCopy paper (SKU DO-PPR) is $45.00   per case of ten reams.\u201d")] + DELTA_OK[1:]
    fake = FakeModel(messy)
    terms, problems = with_fake(fake, lambda: evidence.extract_terms_llm(*delta(), "fake"))
    assert problems == [] and terms["DO-PPR"].unit_price == 45.0 and len(fake.prompts) == 1


def test_model_retry_with_feedback_fixes_a_bogus_tier():
    bogus = [dict(DELTA_OK[0], volume_tier={"more_than_qty": 10, "unit_price": 45.0, "clause": "2.1"})] + DELTA_OK[1:]
    fake = FakeModel(bogus, [DELTA_OK[0]])
    terms, problems = with_fake(fake, lambda: evidence.extract_terms_llm(*delta(), "fake"))
    assert problems == [] and terms["DO-PPR"].volume_tier is None
    assert len(fake.prompts) == 2 and "DO-PPR: volume tier" in fake.prompts[1]
    assert "One entry per SKU in this list: DO-PPR." in fake.prompts[1]      # only the rejected SKU again


def test_model_malformed_answers_never_crash():
    broken = [{"sku": "DO-PPR", "clause": None, "unit_price": "n/a", "volume_tier": {"more_than_qty": None}},
              {"sku": "DO-TNR", "clause": "2.2", "quote": DELTA_OK[1]["quote"], "unit_price": 85, "units_per_box": "lots"},
              "not a dict"]
    fake = FakeModel(ValueError("no JSON"), broken)
    terms, problems = with_fake(fake, lambda: evidence.extract_terms_llm(*delta(), "fake"))
    assert terms == {} and len(problems) == 3 and "malformed" in problems[1], problems


def test_model_cache_asks_only_for_rejected_skus():
    bogus = [dict(DELTA_OK[0], unit_price=50.0)] + DELTA_OK[1:]
    fake = FakeModel(bogus)                                     # DO-PPR is always wrong
    def run():
        ct, co = delta()
        evidence.cached_terms_llm(ct, co, "fake")
        before = len(fake.prompts)
        terms, problems = evidence.cached_terms_llm(ct, co, "fake")
        return terms, problems, fake.prompts[before:]
    terms, problems, later = with_fake(fake, run)
    assert set(terms) == {"DO-TNR", "DO-PEN"} and "DO-PPR" in problems[0]
    assert later and all("One entry per SKU in this list: DO-PPR." in p for p in later)


def test_model_fallback_is_marked_and_strict_mode_reviews():
    inv = parse_invoice_file(DATA_DIR / "demo" / "live" / "04_delta_INV-D-3301.json")
    always_wrong = [dict(DELTA_OK[0], unit_price=50.0)] + DELTA_OK[1:]
    ev = with_fake(FakeModel(always_wrong), lambda: gather_evidence(inv, model="fake"))
    assert ev.problems == [] and ev.terms["DO-PPR"].unit_price == 45.0
    assert ev.terms_source == "model:fake (rules for DO-PPR)"
    strict = with_fake(FakeModel(always_wrong), lambda: gather_evidence(inv, model="fake", fallback=False))
    assert strict.terms["DO-PPR"].unit_price is None and any("DO-PPR" in p for p in strict.problems)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            check(name, fn)
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    sys.exit(1 if FAILED else 0)
