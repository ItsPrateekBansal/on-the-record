"""Invoice Watchdog — dashboard (pipeline steps 12-13).

Run:  streamlit run dashboard/app.py

Reads data/results/. The evidence screen shows why each invoice failed: transaction check next to
the contract check, the clause quoted word for word, the math, and the dispute draft. Only the
Approve button (a person) moves a dispute to data/outbox/, as "ready to send".
"""

import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import audit_log  # noqa: E402
from engine.approval import ApprovalError, approve_dispute, mark_correct  # noqa: E402
from engine.report import CHECK_NAMES  # noqa: E402

DATA = ROOT / "data"
ICON = {"PASS": "✓", "FAIL": "✕", "NEEDS_REVIEW": "?"}
LABEL = {"PASS": "PASS", "FAIL": "FAIL", "NEEDS_REVIEW": "NEEDS REVIEW"}
ORDER = {"FAIL": 0, "NEEDS_REVIEW": 1, "PASS": 2}


def money(x):
    return f"${x:,.2f}"


def load_results():
    rows = []
    for folder in ("discrepancy", "needs_review", "success"):
        for p in (DATA / "results" / folder).glob("*.json"):
            rows.append(json.loads(p.read_text()))
    return sorted(rows, key=lambda r: (ORDER[r["status"]], -r["at_risk"], r["invoice"]))


def check_row(name, value):
    return f"{ICON.get(value, '')} {value}  ·  {name}"


def evidence_screen(r, approver):
    st.markdown(f"## {r.get('vendor') or '?'} · {r['invoice']}")
    if r["status"] == "FAIL":
        st.error(f"POTENTIAL LEAKAGE: {money(r['at_risk'])}  ·  {CHECK_NAMES[r['main_check']]}")
    elif r["status"] == "NEEDS_REVIEW":
        st.warning(f"NEEDS HUMAN REVIEW  ·  {money(r['total'])} under review")
    else:
        st.success("PASSED EVERY CHECK")

    lines, layers = r.get("lines", []), r.get("layers", {})
    if layers:
        left, right = st.columns(2)
        with left:
            st.markdown(f"**TRANSACTION CHECK** — {LABEL[layers['transaction']['status']]}")
            for l in lines:
                st.markdown(f"- PO price {money(l['po_price']) if l['po_price'] is not None else '—'}  ·  "
                            f"invoice price {money(l['unit_price'])} per {l['unit']}")
                before = f"  ·  already billed {l['billed_before']:g}" if l["billed_before"] else ""
                st.markdown(f"- ordered {l['po_qty']:g}  ·  received {l['received']:g}{before}  ·  billed {l['qty']:g}"
                            if l["po_qty"] is not None and l["received"] is not None else "- PO / receipt missing")
            for k, v in layers["transaction"]["checks"].items():
                st.caption(check_row(k, v))
        with right:
            st.markdown(f"**CONTRACT CHECK** — {LABEL[layers['commercial']['status']]}")
            for l in lines:
                st.markdown(f"- invoice price {money(l['unit_price'])}  ·  contract price {money(l['contract_price'])} "
                            f"(clause {l['contract_clause']})")
            st.caption(check_row("contract_price", layers["commercial"]["checks"]["contract_price"]))
            st.markdown(f"**HISTORY** — {LABEL[layers['historical']['status']]}")
            match = layers["historical"]["matched_transaction"]
            st.caption(f"duplicate of {match}" if match else
                       f"previous transactions on this PO: {len(r['evidence']['previous_transactions'])}")

    if r["evidence"].get("clauses"):
        st.markdown("**SOURCE**")
        for num, text in r["evidence"]["clauses"].items():
            st.markdown(f"> **Clause {num}.** {text}")
    if r.get("calculation"):
        st.markdown("**CALCULATION**")
        st.code("\n".join(r["calculation"]), language=None)
    if r.get("reasons"):
        st.markdown("**WHY A PERSON MUST DECIDE**")
        for reason in r["reasons"]:
            st.markdown(f"- {reason}")
    st.markdown("**EXPLANATION**")
    st.write(r.get("explanation", ""))
    if r.get("dispute_draft"):
        with st.expander("Dispute draft", expanded=r["status"] == "FAIL"):
            st.text(r["dispute_draft"])

    contract = DATA / r["evidence"].get("contract", "") if r["evidence"].get("contract") else None
    if contract and contract.exists():
        st.download_button("View contract (PDF)", contract.read_bytes(), contract.name, key=f"c-{r['invoice']}")

    approval = r.get("approval")
    if approval:
        if approval["decision"] == "dispute":
            st.success(f"Approved by {approval['by']} at {approval['at']} — ready to send ({approval['outbox']}). "
                       "Nothing was sent by the agent.")
        else:
            st.success(f"Checked and accepted by {approval['by']} at {approval['at']}.")
        return
    try:
        if r["status"] == "FAIL" and st.button("Approve dispute", type="primary", key=f"a-{r['invoice']}"):
            approve_dispute(r["invoice"], approver, DATA)
            st.rerun()
        if r["status"] == "NEEDS_REVIEW":
            a, b = st.columns(2)
            if a.button("Mark correct", key=f"m-{r['invoice']}"):
                mark_correct(r["invoice"], approver, DATA)
                st.rerun()
            if b.button("Send to dispute", key=f"d-{r['invoice']}"):
                approve_dispute(r["invoice"], approver, DATA)
                st.rerun()
    except ApprovalError as exc:
        st.error(str(exc))


def main():
    st.set_page_config(page_title="Invoice Watchdog", layout="wide")
    st.title("Invoice Watchdog")
    st.caption("Are we actually paying what we agreed to pay?  ·  AI understands · code verifies · humans authorize")

    with st.sidebar:
        approver = st.text_input("Your name (for approvals)", "AP reviewer")
        st.divider()
        if st.button("Verify audit log"):
            ok, n, problem = audit_log.verify(DATA)
            (st.success if ok else st.error)(f"{n} entries · chain intact" if ok else f"{n} entries · {problem}")
        st.caption(f"latest hash: {audit_log.latest_hash(DATA)[:16]}…")
        auto = st.toggle("Auto-refresh every 3 s", value=True)

    @st.fragment(run_every=3 if auto else None)
    def body():
        rows = load_results()
        fails = [r for r in rows if r["status"] == "FAIL"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Invoices audited", len(rows))
        c2.metric("Discrepancies", len(fails))
        c3.metric("Needs review", sum(r["status"] == "NEEDS_REVIEW" for r in rows))
        c4.metric("At risk", money(sum(r["at_risk"] for r in fails)))
        if not rows:
            st.info("No invoices audited yet. Drop invoices into data/inbox/ "
                    "(python3 scripts/drop_invoices.py data/demo/live) with the pipeline running.")
            return
        by_id = {r["invoice"]: r for r in rows}

        def label(inv):
            r = by_id[inv]
            return (f"{ICON[r['status']]} {inv} · {r.get('vendor') or '?'}"
                    + (f" · {money(r['at_risk'])}" if r["status"] == "FAIL" else "")
                    + (" · approved" if r.get("approval") else ""))

        pick = st.selectbox("Invoice", list(by_id), format_func=label, key="pick")
        st.divider()
        evidence_screen(by_id[pick], approver)

    body()


main()
