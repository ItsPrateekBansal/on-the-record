"""Invoice Watchdog — dashboard (pipeline steps 12-13).

Run:  streamlit run dashboard/app.py

Reads data/results/. The evidence screen shows why each invoice failed: transaction check next to
the contract check, the clause quoted word for word, the math, and the dispute draft — plus the
original invoice as received, so the verdict can be checked against the source. Only the
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

# Frosted-glass look: quiet neutrals, one ink accent, no gradients on the
# controls themselves. Everything below only restyles Streamlit's own
# widgets, so if a selector misses on some Streamlit version the page
# still reads fine.
GLASS_CSS = """
<style>
#MainMenu, footer, [data-testid="stDecoration"], [data-testid="stToolbar"] {visibility: hidden; height: 0;}
header[data-testid="stHeader"] {background: transparent;}
.stApp {background: linear-gradient(180deg, #f7f6f3 0%, #edf0f3 100%);}
.stApp::before {
  content: ""; position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background:
    radial-gradient(640px 420px at 12% -5%, rgba(186, 214, 235, 0.55), transparent 70%),
    radial-gradient(720px 520px at 95% 15%, rgba(240, 220, 200, 0.50), transparent 70%),
    radial-gradient(520px 520px at 50% 115%, rgba(205, 222, 210, 0.40), transparent 70%);
}
[data-testid="stAppViewContainer"] {position: relative; z-index: 1; background: transparent;}
[data-testid="stMain"], [data-testid="stMainBlockContainer"] {background: transparent;}
[data-testid="stMainBlockContainer"] {padding-top: 2rem;}
[data-testid="stAppViewContainer"] {
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Inter, Helvetica, Arial, sans-serif;
}
[data-testid="stMarkdownContainer"] p {line-height: 1.6; color: #344054;}
[data-testid="stMarkdownContainer"] h2 {
  font-weight: 650; letter-spacing: -0.02em; color: #0f172a; font-size: 26px; margin: 4px 0 12px;
}
.hero {margin: 6px 0 26px;}
.hero-title {font-size: 42px; font-weight: 650; letter-spacing: -0.03em; color: #0f172a; line-height: 1.1;}
.hero-sub {font-size: 17px; color: #475467; margin-top: 6px;}
.hero-meta {font-size: 13px; color: #98a2b3; margin-top: 8px; letter-spacing: 0.02em;}
.sec {margin: 24px 0 8px; font-size: 12px; font-weight: 600; letter-spacing: 0.1em;
  text-transform: uppercase; color: #667085;}
.sec .st-pass {color: #067647;}
.sec .st-fail {color: #b42318;}
.sec .st-needs_review {color: #b54708;}
div[data-testid="stMetric"] {
  background: rgba(255, 255, 255, 0.55); backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
  border: 1px solid rgba(255, 255, 255, 0.7); border-radius: 20px;
  padding: 18px 20px; box-shadow: 0 8px 30px rgba(30, 60, 90, 0.08);
}
div[data-testid="stMetricLabel"] {color: #667085; font-size: 13px; letter-spacing: 0.04em; text-transform: uppercase;}
div[data-testid="stMetricValue"] {font-weight: 650; color: #0f172a;}
section[data-testid="stSidebar"] {background: rgba(255, 255, 255, 0.45); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);}
section[data-testid="stSidebar"] > div, div[data-testid="stSidebarUserContent"] {background: transparent;}
div[data-testid="stButton"] button, div[data-testid="stDownloadButton"] button,
button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-secondary"] {
  border-radius: 999px; padding: 8px 20px; font-weight: 500;
  background: rgba(255, 255, 255, 0.65); backdrop-filter: blur(10px);
  border: 1px solid rgba(15, 23, 42, 0.12); box-shadow: 0 2px 10px rgba(30, 60, 90, 0.06);
}
div[data-testid="stButton"] button[kind="primary"], button[data-testid="stBaseButton-primary"] {
  background: #0f172a; color: #fff; border-color: #0f172a;
}
div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
  border-radius: 12px; background: rgba(255, 255, 255, 0.65); border-color: rgba(15, 23, 42, 0.10);
}
div[data-testid="stTextInput"] input {
  border-radius: 12px; background: rgba(255, 255, 255, 0.65); border: 1px solid rgba(15, 23, 42, 0.10);
}
div[data-testid="stAlert"] {
  border-radius: 16px; border: 1px solid rgba(255, 255, 255, 0.6);
  backdrop-filter: blur(12px); box-shadow: 0 6px 24px rgba(30, 60, 90, 0.06);
}
div[data-testid="stExpander"] {
  border: 1px solid rgba(255, 255, 255, 0.7); background: rgba(255, 255, 255, 0.50);
  backdrop-filter: blur(12px); border-radius: 16px; overflow: hidden;
  box-shadow: 0 6px 24px rgba(30, 60, 90, 0.05);
}
div[data-testid="stTable"] table {border-collapse: separate; border-spacing: 0;}
div[data-testid="stTable"] th {
  background: rgba(255, 255, 255, 0.7); font-weight: 600; color: #475467;
  border-bottom: 1px solid rgba(15, 23, 42, 0.08);
}
div[data-testid="stTable"] td {border-bottom: 1px solid rgba(15, 23, 42, 0.06);}
hr {border-color: rgba(15, 23, 42, 0.08);}
[data-testid="stCaptionContainer"] {color: #98a2b3;}
</style>
"""


def sec(text, status=None):
    """Quiet small-caps section label, optionally with a coloured status."""
    extra = f' <span class="st-{status.lower()}">· {LABEL[status]}</span>' if status else ""
    st.markdown(f'<div class="sec">{text}{extra}</div>', unsafe_allow_html=True)


def money(x):
    return f"${x:,.2f}"


def load_results():
    rows = []
    for folder in ("discrepancy", "needs_review", "success"):
        for p in (DATA / "results" / folder).glob("*.json"):
            rows.append(json.loads(p.read_text()))
    return sorted(rows, key=lambda r: (ORDER[r["status"]], -r["at_risk"], r["invoice"]))


def filter_rows(rows, status):
    """One status (PASS / FAIL / NEEDS_REVIEW), or None for all."""
    return rows if status is None else [r for r in rows if r["status"] == status]


def check_row(name, value):
    return f"{ICON.get(value, '')} {value}  ·  {name}"


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def invoice_files(r):
    """Original invoice files for a report: (json, pdf), either may be None.

    The pipeline moves each audited file to data/processed/. The PDF twin
    lives in data/demo/ when the run dropped JSONs, so both are searched:
    processed/ first, then the demo folders. Old reports without a file
    field fall back to matching by invoice number.
    """
    names = []
    if r.get("file"):
        names.append(r["file"])
        names.append(Path(r["file"]).stem + ".pdf")
    found = {}
    for d in [DATA / "processed"] + [DATA / "demo" / s for s in ("live", "overnight", "wifi_off")]:
        if not d.exists():
            continue
        for name in names:
            p = d / name
            if p.exists():
                found.setdefault(p.suffix.lower(), p)
        if not names:
            for p in d.glob(f"*{r['invoice']}*"):
                if p.suffix.lower() in (".json", ".pdf"):
                    found.setdefault(p.suffix.lower(), p)
        if ".json" in found and ".pdf" in found:
            break
    return found.get(".json"), found.get(".pdf")


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
            sec("Transaction check", layers['transaction']['status'])
            for l in lines:
                st.markdown(f"- PO price {money(l['po_price']) if l['po_price'] is not None else '—'}  ·  "
                            f"invoice price {money(l['unit_price'])} per {l['unit']}")
                before = f"  ·  already billed {l['billed_before']:g}" if l["billed_before"] else ""
                st.markdown(f"- ordered {l['po_qty']:g}  ·  received {l['received']:g}{before}  ·  billed {l['qty']:g}"
                            if l["po_qty"] is not None and l["received"] is not None else "- PO / receipt missing")
            for k, v in layers["transaction"]["checks"].items():
                st.caption(check_row(k, v))
        with right:
            sec("Contract check", layers['commercial']['status'])
            for l in lines:
                st.markdown(f"- invoice price {money(l['unit_price'])}  ·  contract price {money(l['contract_price'])} "
                            f"(clause {l['contract_clause']})")
            st.caption(check_row("contract_price", layers["commercial"]["checks"]["contract_price"]))
            sec("History", layers['historical']['status'])
            match = layers["historical"]["matched_transaction"]
            st.caption(f"duplicate of {match}" if match else
                       f"previous transactions on this PO: {len(r['evidence']['previous_transactions'])}")

    if r["evidence"].get("clauses"):
        sec("Source")
        for num, text in r["evidence"]["clauses"].items():
            st.markdown(f"> **Clause {num}.** {text}")
    if r.get("calculation"):
        sec("Calculation")
        st.code("\n".join(r["calculation"]), language=None)
    if r.get("reasons"):
        sec("Why a person must decide")
        for reason in r["reasons"]:
            st.markdown(f"- {reason}")
    sec("Explanation")
    st.write(r.get("explanation", ""))
    if r.get("dispute_draft"):
        with st.expander("Dispute draft", expanded=r["status"] == "FAIL"):
            st.text(r["dispute_draft"])

    sec("Invoice, as received")
    inv_json, inv_pdf = invoice_files(r)
    if inv_json:
        raw = json.loads(inv_json.read_text())
        st.markdown(f"{raw.get('invoice_number') or raw.get('invoice_no') or r['invoice']}  ·  "
                    f"{raw.get('vendor') or r.get('vendor') or ''}  ·  "
                    f"PO {raw.get('po_number') or raw.get('po') or '—'}  ·  {raw.get('date') or '—'}")
        rows, lines_sum = [], 0.0
        for l in raw.get("lines", []):
            qty, price = _num(l.get("qty")), _num(l.get("unit_price"))
            amt = (qty or 0) * (price or 0)
            lines_sum += amt
            rows.append({"SKU": l.get("sku") or "—", "Description": l.get("description") or "—",
                         "Qty": l.get("qty"), "Unit price": money(price) if price is not None else "—",
                         "Amount": money(amt)})
        if rows:
            st.table(rows)
        stated = _num(raw.get("total"))
        if stated is not None:
            if abs(stated - lines_sum) > 0.005:
                st.warning(f"Stated total {money(stated)} does not match the lines sum {money(lines_sum)}.")
            else:
                st.caption(f"Stated total {money(stated)} matches the lines.")
    elif inv_pdf:
        st.caption(f"Invoice PDF only ({inv_pdf.name}) — open it below.")
    else:
        st.caption("Original invoice file not found in data/processed/ or data/demo/.")

    sec("Source documents")
    contract = DATA / r["evidence"].get("contract", "") if r["evidence"].get("contract") else None
    if contract and contract.exists():
        st.download_button("View contract (PDF)", contract.read_bytes(), contract.name, key=f"c-{r['invoice']}")
    if inv_json:
        st.download_button("View invoice (JSON)", inv_json.read_bytes(), inv_json.name, key=f"ij-{r['invoice']}")
    if inv_pdf:
        st.download_button("View invoice (PDF)", inv_pdf.read_bytes(), inv_pdf.name, key=f"ip-{r['invoice']}")

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
    st.markdown(GLASS_CSS, unsafe_allow_html=True)
    st.markdown("""
<div class="hero">
  <div class="hero-title">Invoice Watchdog</div>
  <div class="hero-sub">Are we actually paying what we agreed to pay?</div>
  <div class="hero-meta">AI understands · code verifies · humans authorize · runs fully local</div>
</div>
""", unsafe_allow_html=True)

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
        filters = (("All", None), ("✕ Failures", "FAIL"),
                   ("? Needs review", "NEEDS_REVIEW"), ("✓ Passed", "PASS"))
        by_status = dict(filters)
        counts = {k: len(filter_rows(rows, s)) for k, s in filters}
        fchoice = st.selectbox("Filter", [k for k, _ in filters],
                               format_func=lambda k: f"{k} ({counts[k]})",
                               key="status_filter")
        filtered = filter_rows(rows, by_status[fchoice])
        if not filtered:
            st.info("No invoices match this filter.")
            return
        by_id = {r["invoice"]: r for r in filtered}

        def label(inv):
            r = by_id[inv]
            return (f"{ICON[r['status']]} {inv} · {r.get('vendor') or '?'}"
                    + (f" · {money(r['at_risk'])}" if r["status"] == "FAIL" else "")
                    + (" · approved" if r.get("approval") else ""))

        pick = st.selectbox("Invoice", list(by_id), format_func=label, key=f"pick-{fchoice}")
        st.divider()
        evidence_screen(by_id[pick], approver)

    body()


main()
