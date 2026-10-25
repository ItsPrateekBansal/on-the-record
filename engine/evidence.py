"""Invoice Watchdog — load company, read contract, load evidence (pipeline steps 4-6).

Given a parsed Invoice, gathers everything the checks need from data/companies/<vendor>/:
the company record, its contract (every clause), the commercial terms per SKU, the PO,
the goods receipt and the previous transactions. Stdlib only. No decisions are made here:
anything missing is recorded in Evidence.problems for the checks to turn into NEEDS_REVIEW.

Usage (from the repo root):
    from engine.evidence import gather_evidence
    ev = gather_evidence(invoice)             # invoice from parser.invoice_parser

    python3 -m engine.evidence data/demo/live/01_bolt_INV-B-5520.json
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from parser.invoice_parser import Invoice, ParseError, parse_invoice_file  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class EvidenceError(ValueError):
    """Raised when an invoice can't be tied to any company (nothing else can be checked)."""


# ---------------------------------------------------------------- step 4: load company
@dataclass
class Company:
    key: str
    name: str
    folder: Path
    contract_pdf: Path
    contract_txt: Path
    skus: dict            # sku -> {"unit": ..., "clause": ...} from companies/index.json


_SUFFIXES = {"inc", "llc", "co", "corp", "ltd", "company", "the"}


def _norm(name: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    return " ".join(w for w in words if w not in _SUFFIXES)


def load_company(vendor: str, data_dir: Path = DATA_DIR) -> Company:
    """Find the company folder for an invoice's vendor name ("Bolt Industrial" also matches)."""
    index = json.loads((Path(data_dir) / "companies" / "index.json").read_text())
    wanted = _norm(vendor)
    exact = [k for k, c in index.items() if _norm(c["name"]) == wanted]
    partial = [k for k, c in index.items() if wanted and (wanted in _norm(c["name"]) or _norm(c["name"]) in wanted)]
    matches = exact or partial
    if len(matches) != 1:
        raise EvidenceError(f"vendor {vendor!r}: {'no' if not matches else 'ambiguous'} company match {matches}")
    key = matches[0]
    c = index[key]
    folder = Path(data_dir) / c["folder"]
    return Company(key=key, name=c["name"], folder=folder, contract_pdf=folder / c["contract"],
                   contract_txt=folder / c["contract_text"], skus=c["skus"])


# ---------------------------------------------------------------- step 5: read contract
@dataclass
class Contract:
    company: str
    text: str                                       # the whole contract, as given to the model
    sections: dict = field(default_factory=dict)    # "3" -> "Pricing"
    clauses: dict = field(default_factory=dict)     # "3.1" -> clause text, word for word
    effective_from: str | None = None
    effective_to: str | None = None


@dataclass
class Term:
    """Commercial terms for one SKU, each with the clause it came from."""
    sku: str
    unit: str
    clause: str
    quote: str
    unit_price: float | None                        # None -> price not found -> NEEDS_REVIEW
    volume_tier: tuple | None = None                # (more_than_qty, unit_price, clause)
    units_per_box: int | None = None                # e.g. 12 for "boxes of 12 units"


_SECTION = re.compile(r"^(\d+)\. (.+)$")
_CLAUSE = re.compile(r"^(\d+\.\d+) (.+)$")
_MONEY = re.compile(r"\$([\d,]+(?:\.\d{2})?)")
_TERM = re.compile(r"between (\w+ \d{1,2}, \d{4}) and (\w+ \d{1,2}, \d{4})")


def _iso(date_text: str) -> str:
    return datetime.strptime(date_text, "%B %d, %Y").date().isoformat()


def read_contract(company: Company) -> Contract:
    """Load the whole contract text and split it into numbered sections and clauses."""
    text = company.contract_txt.read_text(encoding="utf-8")
    contract = Contract(company=company.key, text=text)
    for line in text.splitlines():
        if m := _CLAUSE.match(line):
            contract.clauses[m.group(1)] = m.group(2)
        elif m := _SECTION.match(line):
            contract.sections[m.group(1)] = m.group(2)
    scope = contract.clauses.get("1.1", "")
    if m := _TERM.search(scope):
        contract.effective_from, contract.effective_to = _iso(m.group(1)), _iso(m.group(2))
    return contract


def extract_terms(contract: Contract, company: Company) -> dict[str, Term]:
    """Rule-based term extraction from the clause text.

    This is the seam for the local model: the model gets contract.text and must return the same
    Term fields, which are then validated against contract.clauses (the quote must be in the text).
    """
    terms = {}
    for sku, info in company.skus.items():
        clause = info["clause"]
        quote = contract.clauses.get(clause, "")
        price = _MONEY.search(quote)
        box = re.search(r"boxes of (\d+) units", quote)
        tier = None
        for num, text in contract.clauses.items():
            if num != clause and sku in text:
                m = re.search(r"more than ([\d,]+) units.*?\$([\d,]+\.\d{2})", text)
                if m:
                    tier = (int(m.group(1).replace(",", "")), float(m.group(2).replace(",", "")), num)
        terms[sku] = Term(sku=sku, unit=info["unit"], clause=clause, quote=quote,
                          unit_price=float(price.group(1).replace(",", "")) if price else None,
                          volume_tier=tier, units_per_box=int(box.group(1)) if box else None)
    return terms


TERMS_PROMPT = """You are reading a supplier contract for an accounts-payable audit.
Return JSON only, no other text, in this shape:
{{"terms": [{{"sku": str, "unit": str, "unit_price": number, "clause": str,
  "quote": str, "units_per_box": int or null,
  "volume_tier": {{"more_than_qty": int, "unit_price": number, "clause": str}} or null}}]}}
One entry per SKU in this list: {skus}.
"clause" is the clause number that sets the SKU's price, e.g. "3.1". "quote" is that clause's
text copied word for word. "unit" is what the price is per (unit, roll, tube, case, box).
"units_per_box": only if the contract itself says how many units a box holds, else null.
"volume_tier": only if another clause gives a different price above a quantity, else null.
Never invent a value that is not written in the contract.

CONTRACT:
{contract}"""


def _amount_in(amount, text: str) -> bool:
    return any(f"${v}" in text for v in (f"{amount:,.2f}", f"{amount:.2f}"))


def _validated_term(sku: str, raw: dict, contract: Contract, unit: str | None = None) -> tuple[Term | None, str | None]:
    """A model term is used only if every value can be found in the contract text.

    unit: the unit the price is per, from companies/index.json (master data). The model's own
    wording ("box of 50") is not used for it. A box size only matters when the price is per unit.
    """
    clause = str(raw.get("clause", "")).strip()
    text = contract.clauses.get(clause)
    if text is None:
        return None, f"clause {clause!r} does not exist"
    quote = str(raw.get("quote", "")).strip()
    if len(quote) < 20 or quote not in text:
        return None, f"quote is not the text of clause {clause}"
    if sku not in text:
        return None, f"clause {clause} does not mention {sku}"
    try:
        price = float(raw["unit_price"])
    except (KeyError, TypeError, ValueError):
        return None, "no unit price"
    if not _amount_in(price, text):
        return None, f"${price:.2f} is not written in clause {clause}"
    unit = (unit or str(raw.get("unit") or "unit")).strip().lower()
    box = raw.get("units_per_box") if unit in ("unit", "each") else None
    if box is not None and not re.search(rf"\b{int(box)}\b", text):
        return None, f"{box} units per box is not written in clause {clause}"
    tier = None
    if raw.get("volume_tier"):
        t = raw["volume_tier"]
        ttext = contract.clauses.get(str(t.get("clause", "")).strip(), "")
        qty = int(t.get("more_than_qty", 0))
        if not (ttext and sku in ttext and _amount_in(float(t.get("unit_price", 0)), ttext)
                and (f"{qty:,}" in ttext or str(qty) in ttext)):
            return None, f"volume tier {t} is not written in the contract"
        tier = (qty, float(t["unit_price"]), str(t["clause"]).strip())
    return Term(sku=sku, unit=unit, clause=clause, quote=text,
                unit_price=price, volume_tier=tier, units_per_box=int(box) if box is not None else None), None


def extract_terms_llm(contract: Contract, company: Company, model: str, skus=None) -> tuple[dict, list]:
    """Step 5 with the local model: the whole contract goes in, terms come out, Python validates.

    Returns (terms, problems). A SKU whose terms fail validation gets unit_price None, which the
    checks turn into NEEDS_REVIEW. Nothing the model says is used unchecked.
    """
    from .llm import generate_json
    skus = list(skus or company.skus)
    problems, terms = [], {}
    try:
        raw_terms = generate_json(TERMS_PROMPT.format(skus=", ".join(skus), contract=contract.text), model)["terms"]
    except (ValueError, KeyError, TypeError) as exc:
        raw_terms, problems = [], [f"model could not read the contract: {exc}"]
    by_sku = {str(t.get("sku", "")).strip(): t for t in raw_terms if isinstance(t, dict)}
    for sku in skus:
        if sku not in company.skus:
            continue
        term, why = (_validated_term(sku, by_sku[sku], contract, company.skus[sku]["unit"])
                     if sku in by_sku else (None, "not returned"))
        if term is None:
            info = company.skus[sku]
            problems.append(f"{sku}: model's contract terms rejected ({why})")
            term = Term(sku=sku, unit=info["unit"], clause=info["clause"],
                        quote=contract.clauses.get(info["clause"], ""), unit_price=None)
        terms[sku] = term
    return terms, problems


# ---------------------------------------------------------------- step 6: load evidence
def load_po(company: Company, po_number: str | None) -> dict | None:
    path = company.folder / "pos" / f"{po_number}.json"
    return json.loads(path.read_text()) if po_number and path.exists() else None


def load_receipt(company: Company, po_number: str | None) -> dict | None:
    for path in sorted((company.folder / "receipts").glob("*.json")):
        receipt = json.loads(path.read_text())
        if po_number and receipt.get("po_number") == po_number:
            return receipt
    return None


def load_transactions(company: Company, po_number: str | None = None,
                      exclude_invoice: str | None = None) -> list[Invoice]:
    """Previous invoices of this company, optionally only those on one PO.

    exclude_invoice: the invoice being audited. Without it, an invoice that was already saved to
    transactions/ would match itself as a duplicate.
    """
    found = []
    for path in sorted((company.folder / "transactions").glob("*.json")):
        try:
            inv = parse_invoice_file(path)
        except ParseError:
            continue
        if inv.invoice_no == exclude_invoice:
            continue
        if po_number is None or inv.po == po_number:
            found.append(inv)
    return found


@dataclass
class Evidence:
    invoice: Invoice
    company: Company
    contract: Contract
    terms: dict                                     # sku -> Term
    po: dict | None
    receipt: dict | None
    previous: list                                  # previous Invoices on the same PO
    problems: list = field(default_factory=list)    # reasons the checks can't fully decide
    terms_source: str = "rules"                     # "rules" or "model:<name>"


def gather_evidence(invoice: Invoice, data_dir: Path = DATA_DIR, model: str | None = None) -> Evidence:
    """Steps 4-6 for one invoice. Raises EvidenceError only if the vendor is unknown.

    model: read the contract with the local model (validated); None uses the rule-based reader.
    """
    company = load_company(invoice.vendor, data_dir)
    contract = read_contract(company)
    problems = []
    if model:
        wanted = [l.sku for l in invoice.lines if l.sku in company.skus]
        terms, problems = extract_terms_llm(contract, company, model, wanted)
    else:
        terms = extract_terms(contract, company)
    po = load_po(company, invoice.po)
    receipt = load_receipt(company, invoice.po)
    previous = load_transactions(company, invoice.po, exclude_invoice=invoice.invoice_no)

    if invoice.po is None:
        problems.append("invoice has no PO number")
    elif po is None:
        problems.append(f"PO {invoice.po} not found for {company.name}")
    if invoice.po and receipt is None:
        problems.append(f"no goods receipt for {invoice.po}")
    po_skus = {l["sku"] for l in po["lines"]} if po else set()
    for line in invoice.lines:
        if line.sku not in terms:
            problems.append(f"{line.sku}: not in {company.name}'s contract")
        elif terms[line.sku].unit_price is None and not model:
            problems.append(f"{line.sku}: no price found in clause {terms[line.sku].clause}")
        if po and line.sku not in po_skus:
            problems.append(f"{line.sku}: not on {invoice.po}")
    return Evidence(invoice, company, contract, terms, po, receipt, previous, problems,
                    f"model:{model}" if model else "rules")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: python3 -m engine.evidence <invoice.json>")
    ev = gather_evidence(parse_invoice_file(sys.argv[1]))
    print(f"{ev.invoice.invoice_no}  {ev.company.name}  ({ev.company.folder})")
    print(f"  contract: {len(ev.contract.clauses)} clauses, {ev.contract.effective_from} to {ev.contract.effective_to}")
    for line in ev.invoice.lines:
        t = ev.terms.get(line.sku)
        if t:
            extra = f", tier >{t.volume_tier[0]} -> ${t.volume_tier[1]:.2f} ({t.volume_tier[2]})" if t.volume_tier else ""
            extra += f", {t.units_per_box} per box" if t.units_per_box else ""
            print(f"  {line.sku}: billed {line.qty:g} {line.unit or t.unit} x ${line.unit_price:.2f} | "
                  f"contract ${t.unit_price:.2f}/{t.unit} (clause {t.clause}{extra})")
            print(f"      \"{t.quote}\"")
    print(f"  PO: {ev.po['po_number'] if ev.po else None} | receipt: {ev.receipt['receipt_id'] if ev.receipt else None}")
    print(f"  previous transactions on this PO: {[p.invoice_no for p in ev.previous] or 'none'}")
    print(f"  problems: {ev.problems or 'none'}")


if __name__ == "__main__":
    main()
