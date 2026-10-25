"""Invoice Watchdog — human approval (pipeline step 13).

Only these functions, called from the dashboard by a person, write to data/outbox/. The agent
never calls them and nothing here sends email: an approved dispute is "ready to send".

  approve_dispute   FAIL invoice (or a reviewed one a person decided to dispute) -> outbox/
  mark_correct      NEEDS_REVIEW invoice a person checked and accepts -> results/success/
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import audit_log
from .report import load_result, write_result


class ApprovalError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def approve_dispute(invoice_no: str, approver: str, data_dir) -> Path:
    result, _ = load_result(invoice_no, data_dir)
    if result is None:
        raise ApprovalError(f"{invoice_no}: no audit result")
    if not approver.strip():
        raise ApprovalError("approver name is required")
    if result["status"] == "PASS":
        raise ApprovalError(f"{invoice_no} passed every check; there is nothing to dispute")
    if result.get("approval"):
        raise ApprovalError(f"{invoice_no} was already approved by {result['approval']['by']}")
    draft = result.get("dispute_draft") or (
        f"Subject: Invoice {invoice_no} ({result['po']}) under review\n\n"
        f"Dear {result['vendor']} accounts team,\n\nWe cannot approve invoice {invoice_no} yet: "
        + " ".join(result["reasons"]) + "\nPlease contact us to clarify.\n\n"
        "Regards,\nAccounts Payable, Harbor Ridge Manufacturing, Inc.\n")
    outbox = Path(data_dir) / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    path = outbox / f"{invoice_no}_dispute.txt"
    when = _now()
    path.write_text(f"STATUS: READY TO SEND (approved by {approver} at {when}). Not sent by the agent.\n\n{draft}")
    result["approval"] = {"decision": "dispute", "by": approver, "at": when, "outbox": f"outbox/{path.name}"}
    write_result(result, data_dir)
    audit_log.append(data_dir, "dispute_approved", invoice_no, by=approver, outbox=f"outbox/{path.name}")
    return path


def mark_correct(invoice_no: str, approver: str, data_dir) -> Path:
    result, _ = load_result(invoice_no, data_dir)
    if result is None or result["status"] != "NEEDS_REVIEW":
        raise ApprovalError(f"{invoice_no}: only invoices that need review can be marked correct")
    if not approver.strip():
        raise ApprovalError("approver name is required")
    when = _now()
    result.update(status="PASS", result_folder="results/success", at_risk=0.0, amount_under_review=0.0,
                  approval={"decision": "correct", "by": approver, "at": when})
    path = write_result(result, data_dir)
    tx = Path(data_dir) / "companies" / result["vendor_key"] / "transactions" / f"{invoice_no}.json"
    if tx.exists():                                    # a person accepted it, so it now counts as billed
        body = json.loads(tx.read_text())
        tx.write_text(json.dumps(body | {"status": "PASS", "reviewed_by": approver}, indent=2))
    audit_log.append(data_dir, "marked_correct", invoice_no, by=approver)
    return path
