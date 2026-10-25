"""Invoice Watchdog — note the transaction, report, explain, alert (pipeline steps 8-11).

  save_transaction  step 8:  companies/<vendor>/transactions/<invoice>.json
  write_result      step 9:  results/success|discrepancy|needs_review/<invoice>.json
  explain / draft_dispute  step 10: template text built only from the verified result.
                    The local model (Nemotron / Qwen) will later rewrite these; it must not
                    change any number, clause or verdict.
  alert             step 11: one short line for Slack. Prices, clauses and drafts stay local.
                    Alerts are appended to data/alerts.jsonl; the OpenClaw agent posts them.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .checks import RESULT_FOLDERS

CHECK_NAMES = {
    "contract_price": "price above contract",
    "po_quantity": "quantity above PO",
    "receipt_quantity": "quantity above goods received",
    "po_price": "price differs from PO",
    "duplicate": "possible duplicate",
    "unit_of_measure": "unclear unit of measure",
    "missing_evidence": "missing PO, receipt or contract term",
}


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- step 8
def save_transaction(invoice, result: dict, data_dir) -> Path:
    """Record the audited invoice in the company's transactions/ folder.

    Call this only after the evidence was gathered, or the invoice would be in its own history.
    Only status PASS transactions count as billed in later checks.
    """
    path = Path(data_dir) / "companies" / result["vendor_key"] / "transactions" / f"{invoice.invoice_no}.json"
    body = {"invoice_number": invoice.invoice_no, "vendor": invoice.vendor, "po_number": invoice.po,
            "date": invoice.date, "total": invoice.total,
            "lines": [{"sku": l.sku, "description": l.description, "qty": l.qty, "unit": l.unit,
                       "unit_price": l.unit_price} for l in invoice.lines],
            "status": result["status"], "audited_at": _now()}
    path.write_text(json.dumps(body, indent=2))
    return path


# ---------------------------------------------------------------- step 9
def write_result(result: dict, data_dir) -> Path:
    results = Path(data_dir) / "results"
    for folder in RESULT_FOLDERS.values():                 # a re-audit replaces the old verdict
        (results / folder / f"{result['invoice']}.json").unlink(missing_ok=True)
    path = Path(data_dir) / result["result_folder"] / f"{result['invoice']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2))
    return path


def load_result(invoice_no: str, data_dir) -> tuple[dict, Path] | tuple[None, None]:
    for folder in RESULT_FOLDERS.values():
        path = Path(data_dir) / "results" / folder / f"{invoice_no}.json"
        if path.exists():
            return json.loads(path.read_text()), path
    return None, None


# ---------------------------------------------------------------- step 10
def explain(result: dict) -> str:
    who = f"{result['vendor']} invoice {result['invoice']} ({_money(result['total'])}, {result['po']})"
    if result["status"] == "PASS":
        return f"{who} passed every check: prices match the PO and the contract, quantities match the PO and the goods receipt, and it is not a duplicate."
    if result["status"] == "NEEDS_REVIEW":
        return f"{who} needs a person to decide. " + " ".join(r[0].upper() + r[1:] + "." for r in result["reasons"])
    t = result["layers"]["transaction"]["status"]
    headline = CHECK_NAMES[result["main_check"]]
    text = f"{who}: {headline}, {_money(result['at_risk'])} at risk."
    if result["main_check"] == "contract_price" and t == "PASS":
        text += " The invoice matches the purchase order, so a PO match passes, but the price breaks the contract."
    return text + " " + " ".join(c + "." for c in result["calculation"])


def draft_dispute(result: dict, vendor_email: str | None = None) -> str | None:
    if result["status"] != "FAIL":
        return None
    quotes = "\n".join(f'  Clause {num}: "{text}"' for num, text in result["evidence"]["clauses"].items())
    math = "\n".join(f"  - {c}" for c in result["calculation"])
    return (f"To: {vendor_email or result['vendor']}\n"
            f"Subject: Dispute of invoice {result['invoice']} ({result['po']})\n\n"
            f"Dear {result['vendor']} accounts team,\n\n"
            f"We are disputing invoice {result['invoice']} dated {result['date']} for {_money(result['total'])} "
            f"under our Master Supply Agreement.\n\n"
            f"Issue: {CHECK_NAMES[result['main_check']]}.\n{math}\n\n"
            f"Relevant terms of our agreement:\n{quotes}\n\n"
            f"Amount in dispute: {_money(result['at_risk'])}. Please send a corrected invoice; the undisputed "
            f"amount will be paid on the agreed terms.\n\n"
            f"Regards,\nAccounts Payable, Harbor Ridge Manufacturing, Inc.\n")


# ---------------------------------------------------------------- step 11
def alert_text(result: dict) -> str | None:
    if result["status"] == "FAIL":
        return f"{result['vendor']} · {result['invoice']} · {_money(result['at_risk'])} at risk · {CHECK_NAMES[result['main_check']]}"
    if result["status"] == "NEEDS_REVIEW":
        return f"{result['vendor']} · {result['invoice']} · needs human review · {CHECK_NAMES[result['main_check']]}"
    return None                                            # clean invoices make no noise


def alert(result: dict, data_dir) -> str | None:
    text = alert_text(result)
    if text:
        with open(Path(data_dir) / "alerts.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"time": _now(), "invoice": result["invoice"], "text": text, "posted": False}) + "\n")
    return text
