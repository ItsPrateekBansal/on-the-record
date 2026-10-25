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
"sku": exactly the SKU code from the list. "clause": only the clause number that sets the SKU's
price, e.g. "3.1". "quote": that clause's text copied word for word. "unit": what the price is
per (unit, roll, tube, case, box).
"units_per_box": only if the price is per single unit AND the contract says how many units a box
holds; null otherwise. A pack size such as "case of ten reams" or "box of 50" when the price is
already per case or per box is NOT units_per_box and NOT a volume tier.
"volume_tier": only if a separate clause gives a different price above a stated quantity; else null.
Never invent a value that is not written in the contract.
{feedback}
CONTRACT:
{contract}"""

FEEDBACK = """Your previous answer was rejected for these SKUs. Answer again for them only, and use
null for anything the contract does not state:
{lines}
"""

_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})


def _squash(text: str) -> str:
    """Whitespace and typographic quotes don't count as differences."""
    return " ".join(str(text).translate(_QUOTES).split()).strip(" \"'")


def _number(value) -> float:
    return float(str(value).replace("$", "").replace(",", "").strip())


def _amount_in(amount, text: str) -> bool:
    return any(f"${v}" in text for v in (f"{amount:,.2f}", f"{amount:.2f}"))


def _clause_number(value) -> str:
    m = re.search(r"\d+\.\d+", str(value or ""))       # "Clause 2.1", "Section 2.1" -> "2.1"
    return m.group(0) if m else ""


def _validated_term(sku: str, raw: dict, contract: Contract, unit: str | None = None) -> tuple[Term | None, str | None]:
    """A model term is used only if every value can be found in the contract text.

    unit: the unit the price is per, from companies/index.json (master data). The model's own
    wording ("box of 50") is not used for it. A box size only matters when the price is per unit.
    Formatting ("Clause 2.1", curly quotes, "$45.00" as text) is normalized; facts are not.
    """
    try:
        clause = _clause_number(raw.get("clause"))
        text = contract.clauses.get(clause)
        if text is None:
            return None, f"clause {raw.get('clause')!r} does not exist"
        quote = _squash(raw.get("quote", ""))
        if len(quote) < 20 or quote not in _squash(text):
            return None, f"quote is not the text of clause {clause}"
        if sku not in text:
            return None, f"clause {clause} does not mention {sku}"
        try:
            price = _number(raw["unit_price"])
        except (KeyError, TypeError, ValueError):
            return None, "no unit price"
        if not _amount_in(price, text):
            return None, f"${price:.2f} is not written in clause {clause}"
        unit = (unit or str(raw.get("unit") or "unit")).strip().lower()
        box = raw.get("units_per_box") if unit in ("unit", "each") else None
        if box is not None:
            box = int(_number(box))
            if not re.search(rf"\b{box}\b", text):
                return None, f"{box} units per box is not written in clause {clause}"
        tier = None
        t = raw.get("volume_tier")
        if isinstance(t, dict) and any(v is not None for v in t.values()):
            tclause = _clause_number(t.get("clause"))
            ttext = contract.clauses.get(tclause, "")
            qty, tprice = int(_number(t.get("more_than_qty"))), _number(t.get("unit_price"))
            if not (ttext and sku in ttext and _amount_in(tprice, ttext)
                    and (f"{qty:,}" in ttext or str(qty) in ttext)):
                return None, f"volume tier {t} is not written in the contract"
            tier = (qty, tprice, tclause)
    except (TypeError, ValueError) as exc:                 # any malformed field: reject, never crash
        return None, f"malformed answer ({exc})"
    return Term(sku=sku, unit=unit, clause=clause, quote=text,
                unit_price=price, volume_tier=tier, units_per_box=box), None


def _match_sku(value, skus) -> str | None:
    value = str(value or "")
    return next((s for s in skus if s == value.strip() or re.search(rf"(?<![\w-]){re.escape(s)}(?![\w-])", value)), None)


def extract_terms_llm(contract: Contract, company: Company, model: str, skus=None,
                      retries: int = 2) -> tuple[dict, list]:
    """Step 5 with the local model: the whole contract goes in, terms come out, Python validates.

    Rejected SKUs are asked again (up to `retries` times) with the reason, so the model can
    correct itself. Returns (accepted terms, problems for SKUs still rejected). Nothing the model
    says is used unchecked.
    """
    from .llm import generate_json
    wanted = [s for s in (skus or company.skus) if s in company.skus]
    accepted, why_not = {}, {}
    for _ in range(1 + retries):
        todo = [s for s in wanted if s not in accepted]
        if not todo:
            break
        feedback = FEEDBACK.format(lines="\n".join(f"- {s}: {why_not[s]}" for s in todo)) if why_not else ""
        try:
            raw_terms = generate_json(TERMS_PROMPT.format(skus=", ".join(todo), feedback=feedback,
                                                          contract=contract.text), model)["terms"]
            raw_terms = raw_terms if isinstance(raw_terms, list) else []
        except (ValueError, KeyError, TypeError) as exc:
            why_not.update({s: f"no usable JSON ({exc})" for s in todo})
            continue
        by_sku = {}
        for t in raw_terms:
            if isinstance(t, dict) and (s := _match_sku(t.get("sku"), todo)):
                by_sku.setdefault(s, t)
        for s in todo:
            term, why = (_validated_term(s, by_sku[s], contract, company.skus[s]["unit"])
                         if s in by_sku else (None, "not returned"))
            if term:
                accepted[s] = term
            else:
                why_not[s] = why
    problems = [f"{s}: model's contract terms rejected ({why_not[s]})" for s in wanted if s not in accepted]
    return accepted, problems


_TERMS_CACHE: dict = {}       # (company, model, contract text) -> {sku: accepted Term}


def cached_terms_llm(contract: Contract, company: Company, model: str) -> tuple[dict, list]:
    """Model terms for all of the company's SKUs; accepted SKUs are read once per run.

    Contracts don't change between invoices. Only SKUs that were rejected are asked again.
    """
    cache = _TERMS_CACHE.setdefault((company.key, model, contract.text), {})
    missing = [s for s in company.skus if s not in cache]
    problems = []
    if missing:
        terms, problems = extract_terms_llm(contract, company, model, missing)
        cache.update(terms)
    return dict(cache), list(problems)


def check_contracts(model: str, data_dir: Path = DATA_DIR, fallback: bool = True) -> list[str]:
    """Read every company's contract with the model before any invoice arrives. One line each."""
    index = json.loads((Path(data_dir) / "companies" / "index.json").read_text())
    report = []
    for c in index.values():
        co = load_company(c["name"], data_dir)
        terms, problems = cached_terms_llm(read_contract(co), co, model)
        line = f"{co.key}: {len(terms)}/{len(co.skus)} contract terms accepted from {model}"
        if problems:
            line += (" — rules used for the rest: " if fallback else " — NEEDS REVIEW: ") + "; ".join(problems)
        report.append(line)
    return report


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


def gather_evidence(invoice: Invoice, data_dir: Path = DATA_DIR, model: str | None = None,
                    fallback: bool = True) -> Evidence:
    """Steps 4-6 for one invoice. Raises EvidenceError only if the vendor is unknown.

    model: read the contract with the local model (validated, with retries); None uses the
    rule-based reader. fallback: for SKUs the model still gets wrong, use the rule-based reader
    and say so in terms_source; without it, those SKUs go to NEEDS_REVIEW.
    """
    company = load_company(invoice.vendor, data_dir)
    contract = read_contract(company)
    problems = []
    source = f"model:{model}" if model else "rules"
    if model:
        terms, problems = cached_terms_llm(contract, company, model)
        rejected = [s for s in company.skus if s not in terms]
        if rejected and fallback:                  # model still rejected after retries: rules,
            rules = extract_terms(contract, company)   # marked on the result, never silent
            terms.update({s: rules[s] for s in rejected})
            problems = []
            source += f" (rules for {', '.join(rejected)})"
        for s in rejected:
            if s not in terms:
                info = company.skus[s]
                terms[s] = Term(sku=s, unit=info["unit"], clause=info["clause"],
                                quote=contract.clauses.get(info["clause"], ""), unit_price=None)
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
    return Evidence(invoice, company, contract, terms, po, receipt, previous, problems, source)


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
