"""Invoice Watchdog — the checks (pipeline step 7).

Plain Python decides every PASS / FAIL / NEEDS_REVIEW and every dollar amount; no model is
involved. Three layers:
  transaction  po_price, po_quantity, receipt_quantity (net of what earlier invoices on the
               same PO already billed)
  commercial   contract_price (volume tiers and units per box from the contract)
  historical   duplicate (same PO and amount as a previous transaction)

Only previous transactions with status PASS count as billed: a disputed invoice was never paid.

Usage:
    from engine.checks import run_checks
    result = run_checks(evidence)       # evidence from engine.evidence.gather_evidence
"""

from __future__ import annotations

import re

from .evidence import Evidence

CHECKS = ("po_price", "po_quantity", "receipt_quantity", "contract_price", "duplicate")
TRANSACTION = ("po_price", "po_quantity", "receipt_quantity")
# when several checks fail, the headline is the first of these
MAIN_CHECK_ORDER = ("duplicate", "contract_price", "po_quantity", "receipt_quantity", "po_price")
RESULT_FOLDERS = {"PASS": "success", "FAIL": "discrepancy", "NEEDS_REVIEW": "needs_review"}
UNIT_ALIASES = {"each": "unit", "ea": "unit", "pc": "unit", "pcs": "unit", "units": "unit"}
CENT = 0.005


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _unit(name: str) -> str:
    name = name.strip().lower()
    return UNIT_ALIASES.get(name, name)


def to_contract_units(line, term):
    """Invoice line in the contract's unit: (qty, unit_price, None) or (None, None, reason)."""
    billed, priced = _unit(line.unit or term.unit), _unit(term.unit)
    if billed == priced:
        return line.qty, line.unit_price, None
    box = re.fullmatch(r"box(?:es)?\s*(?:\(\s*(\d+)\s*\))?", billed)
    if box and term.units_per_box:
        if box.group(1) and int(box.group(1)) != term.units_per_box:
            return None, None, (f"{line.sku}: billed per box of {box.group(1)}, but clause {term.clause} "
                                f"says boxes of {term.units_per_box}")
        factor = term.units_per_box
        return line.qty * factor, round(line.unit_price / factor, 4), None
    return None, None, (f"{line.sku}: billed per '{line.unit}', but clause {term.clause} prices per "
                        f"{term.unit} and does not define a '{line.unit}'")


def _clause_containing(contract, phrase):
    return next((num for num, text in contract.clauses.items() if phrase in text.lower()), None)


def _counts(transaction) -> bool:
    return transaction.raw.get("status", "PASS") == "PASS"


def run_checks(ev: Evidence) -> dict:
    inv, contract = ev.invoice, ev.contract
    checks = {c: "PASS" for c in CHECKS}
    reasons, clauses, calculation, lines = list(ev.problems), [], [], []
    unit_problem = False
    at_risk = 0.0

    counted = [p for p in ev.previous if _counts(p)]
    billed_before = {}
    for p in counted:
        for pl in p.lines:
            if pl.sku in ev.terms:
                q, _, _ = to_contract_units(pl, ev.terms[pl.sku])
                if q is not None:
                    billed_before[pl.sku] = billed_before.get(pl.sku, 0) + q
    po_lines = {l["sku"]: l for l in ev.po["lines"]} if ev.po else {}
    received = {l["sku"]: l["qty_received"] for l in ev.receipt["lines"]} if ev.receipt else {}
    qty_clause = _clause_containing(contract, "in excess of the purchase order")

    if inv.date and contract.effective_from and not (contract.effective_from <= inv.date <= contract.effective_to):
        reasons.append(f"invoice date {inv.date} is outside the contract term "
                       f"({contract.effective_from} to {contract.effective_to}, clause 1.1)")

    for line in inv.lines:
        term = ev.terms.get(line.sku)
        if term is None or term.unit_price is None:
            continue                                # already recorded in ev.problems
        qty, price, why = to_contract_units(line, term)
        if why:
            unit_problem = True
            reasons.append(why)
            clauses.append(term.clause)
            continue
        cprice, cclause = term.unit_price, term.clause
        if term.volume_tier and qty > term.volume_tier[0]:
            cprice, cclause = term.volume_tier[1], term.volume_tier[2]
        clauses.append(cclause)
        pl, rq = po_lines.get(line.sku), received.get(line.sku)
        detail = {"sku": line.sku, "billed_qty": line.qty, "billed_unit": line.unit or term.unit,
                  "billed_price": line.unit_price, "qty": qty, "unit": term.unit, "unit_price": price,
                  "contract_price": cprice, "contract_clause": cclause,
                  "po_qty": pl["qty"] if pl else None, "po_price": pl["unit_price"] if pl else None,
                  "received": rq, "billed_before": billed_before.get(line.sku, 0)}
        lines.append(detail)
        if line.unit and qty != line.qty:
            calculation.append(f"{line.sku}: {line.qty:g} {line.unit} at {_money(line.unit_price)} = "
                               f"{qty:g} {term.unit}s at {_money(price)} per {term.unit} (clause {term.clause})")
        if price > cprice + CENT:
            checks["contract_price"] = "FAIL"
            calculation.append(f"{line.sku}: billed {_money(price)} per {term.unit}, contract clause {cclause} says "
                               f"{_money(cprice)} -> {qty:g} x {_money(price - cprice)} = {_money(qty * (price - cprice))}")
        if pl is None or rq is None:
            continue                                # missing PO / receipt: already in ev.problems
        prior = billed_before.get(line.sku, 0)
        po_left, rec_left = max(0, pl["qty"] - prior), max(0, rq - prior)
        if abs(price - pl["unit_price"]) > CENT:
            checks["po_price"] = "FAIL"
            calculation.append(f"{line.sku}: billed {_money(price)}, {ev.po['po_number']} says {_money(pl['unit_price'])}")
        if qty > po_left:
            checks["po_quantity"] = "FAIL"
            if qty_clause:
                clauses.append(qty_clause)
            before = f", earlier invoices already billed {prior:g}, so {po_left:g} left" if prior else ""
            calculation.append(f"{line.sku}: billed {qty:g}, {ev.po['po_number']} ordered {pl['qty']:g}{before} "
                               f"-> {qty - po_left:g} too many")
        if qty > rec_left:
            checks["receipt_quantity"] = "FAIL"
            calculation.append(f"{line.sku}: billed {qty:g}, receipt {ev.receipt['receipt_id']} received {rq:g}"
                               + (f" ({rec_left:g} not yet billed)" if prior else ""))
        payable = min(qty, po_left, rec_left) * min(price, cprice)
        at_risk += qty * price - payable

    dup = next((p for p in counted if p.po == inv.po and abs(p.total - inv.total) < CENT), None)
    if dup:
        checks["duplicate"] = "FAIL"
        dclause = _clause_containing(contract, "same goods more than once")
        if dclause:
            clauses.append(dclause)
        calculation.append(f"same PO {inv.po} and same {_money(inv.total)} as previous transaction "
                           f"{dup.invoice_no} -> whole invoice {_money(inv.total)}")
        at_risk = inv.total

    review = bool(reasons)
    if review:
        for k in CHECKS[:4]:
            if checks[k] == "PASS":
                checks[k] = "NEEDS_REVIEW"

    def layer(*names):
        vals = [checks[n] for n in names]
        return "FAIL" if "FAIL" in vals else "NEEDS_REVIEW" if "NEEDS_REVIEW" in vals else "PASS"

    status = "FAIL" if "FAIL" in checks.values() else "NEEDS_REVIEW" if review else "PASS"
    main_check = next((c for c in MAIN_CHECK_ORDER if checks[c] == "FAIL"), None)
    if status == "NEEDS_REVIEW":
        main_check = "unit_of_measure" if unit_problem else "missing_evidence"
    at_risk = round(at_risk, 2) if status == "FAIL" else 0.0
    key = ev.company.key
    return {
        "invoice": inv.invoice_no,
        "vendor": ev.company.name,
        "vendor_key": key,
        "po": inv.po,
        "date": inv.date,
        "total": inv.total,
        "status": status,
        "main_check": main_check,
        "at_risk": at_risk,
        "amount_under_review": inv.total if status == "NEEDS_REVIEW" else 0.0,
        "layers": {
            "transaction": {"status": layer(*TRANSACTION), "checks": {k: checks[k] for k in TRANSACTION}},
            "commercial": {"status": layer("contract_price"), "checks": {"contract_price": checks["contract_price"]}},
            "historical": {"status": layer("duplicate"), "checks": {"duplicate": checks["duplicate"]},
                           "matched_transaction": dup.invoice_no if dup else None},
        },
        "result_folder": f"results/{RESULT_FOLDERS[status]}",
        "evidence": {
            "po": f"companies/{key}/pos/{ev.po['po_number']}.json" if ev.po else None,
            "receipt": f"companies/{key}/receipts/{ev.receipt['receipt_id']}.json" if ev.receipt else None,
            "previous_transactions": [f"companies/{key}/transactions/{p.invoice_no}.json" for p in ev.previous],
            "contract": f"companies/{key}/{ev.company.contract_pdf.name}",
            "clauses": {c: contract.clauses[c] for c in dict.fromkeys(clauses) if c in contract.clauses},
        },
        "reasons": reasons,
        "calculation": calculation,
        "lines": lines,
    }
