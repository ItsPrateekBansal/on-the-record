"""Invoice Watchdog — dashboard (pipeline steps 12-13).

Run:  streamlit run dashboard/app.py

Reads data/results/. One page: trust badges and totals on top, the live feed of audited invoices
on the left, and the evidence for the selected invoice on the right: the transaction, contract
and history checks side by side, the clause quoted word for word, the math, the original invoice
and the dispute draft. Only a person clicking Approve moves a dispute to data/outbox/, as
"ready to send". The dashboard never decides anything: it only shows what the pipeline wrote.
Fully offline: no web fonts, scripts or CDNs.
"""

import html
import json
import os
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
LABEL = {"PASS": "PASS", "FAIL": "FAIL", "NEEDS_REVIEW": "REVIEW"}
FILTERS = {"ALL": "All", "FAIL": "Failures", "NEEDS_REVIEW": "Needs review", "PASS": "Passed"}

# Calm, finance-grade look: near-white page, one ink colour, status colours only for meaning.
# System fonts only, so the page looks the same with wifi off.
CSS = """
<style>
#MainMenu, footer, [data-testid="stDecoration"], [data-testid="stToolbar"] {visibility: hidden; height: 0;}
header[data-testid="stHeader"] {background: transparent;}
.stApp {background: #f8fafc;}
[data-testid="stMainBlockContainer"] {padding-top: 1.4rem; max-width: 1500px;}
[data-testid="stAppViewContainer"], .stApp {
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Inter, Helvetica, Arial, sans-serif;
  color: #0f172a;
}
@keyframes fadein {from {opacity: 0; transform: translateY(4px);} to {opacity: 1; transform: none;}}
@keyframes slidein {from {opacity: 0; transform: translateX(-10px);} to {opacity: 1; transform: none;}}

.top {display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; flex-wrap: wrap; margin-bottom: 18px;}
.brand {font-size: 30px; font-weight: 650; letter-spacing: -0.02em;}
.tagline {font-size: 16px; color: #475467; margin-top: 2px;}
.principle {font-size: 13px; color: #98a2b3; margin-top: 4px; letter-spacing: 0.02em;}
.badges {display: flex; gap: 8px; flex-wrap: wrap;}
.badge {font-size: 13px; padding: 6px 12px; border-radius: 999px; background: #fff;
  border: 1px solid #e4e7ec; color: #344054; white-space: nowrap;}
.badge b {font-weight: 600; color: #0f172a;}
.badge.ok {border-color: #abefc6; background: #ecfdf3; color: #067647;}
.badge.bad {border-color: #fecdca; background: #fef3f2; color: #b42318;}

.metrics {display: grid; grid-template-columns: 1.6fr 1fr 1fr 1fr; gap: 14px; margin-bottom: 22px;}
.tile {background: #fff; border: 1px solid #eaecf0; border-radius: 18px; padding: 16px 20px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);}
.tile .k {font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: #667085;}
.tile .v {font-size: 40px; font-weight: 650; letter-spacing: -0.02em; font-variant-numeric: tabular-nums;
  margin-top: 4px; animation: fadein 0.5s ease;}
.tile.risk .v {font-size: 48px; color: #b42318;}

.sec {margin: 22px 0 8px; font-size: 12px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: #667085;}

.card {background: #fff; border: 1px solid #eaecf0; border-left: 4px solid #d0d5dd; border-radius: 14px;
  padding: 10px 14px; animation: slidein 0.4s ease; margin-bottom: 2px;}
.card.FAIL {border-left-color: #b42318;}
.card.NEEDS_REVIEW {border-left-color: #b54708;}
.card.PASS {border-left-color: #067647;}
.card.sel {box-shadow: 0 0 0 2px #0f172a;}
.card .row1 {display: flex; justify-content: space-between; align-items: baseline; gap: 10px;}
.card .who {font-size: 15px; font-weight: 600;}
.card .amt {font-size: 15px; font-weight: 600; font-variant-numeric: tabular-nums; color: #b42318; white-space: nowrap;}
.card .row2 {font-size: 13px; color: #667085; margin-top: 2px;}
.chip {display: inline-block; font-size: 11px; font-weight: 600; letter-spacing: 0.06em; padding: 2px 8px;
  border-radius: 999px; margin-right: 6px; vertical-align: 1px;}
.chip.FAIL {background: #fef3f2; color: #b42318;}
.chip.NEEDS_REVIEW {background: #fffaeb; color: #b54708;}
.chip.PASS {background: #ecfdf3; color: #067647;}

.verdict {border-radius: 18px; padding: 18px 22px; animation: fadein 0.5s ease;}
.verdict .t {font-size: 24px; font-weight: 650; letter-spacing: -0.01em; font-variant-numeric: tabular-nums;}
.verdict .s {font-size: 15px; margin-top: 6px; line-height: 1.55;}
.verdict.FAIL {background: #fef3f2; border: 1px solid #fecdca; color: #7a271a;}
.verdict.FAIL .t {color: #b42318;}
.verdict.NEEDS_REVIEW {background: #fffaeb; border: 1px solid #fedf89; color: #7a2e0e;}
.verdict.NEEDS_REVIEW .t {color: #b54708;}
.verdict.PASS {background: #ecfdf3; border: 1px solid #abefc6; color: #054f31;}
.verdict.PASS .t {color: #067647;}
.who-line {font-size: 14px; color: #667085; margin: 0 0 10px;}

.checks {display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 14px;}
.check {background: #fff; border: 1px solid #eaecf0; border-top: 5px solid #d0d5dd; border-radius: 16px; padding: 14px 16px;}
.check.FAIL {border-top-color: #b42318;}
.check.NEEDS_REVIEW {border-top-color: #b54708;}
.check.PASS {border-top-color: #067647;}
.check .name {font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: #667085;}
.check .state {font-size: 26px; font-weight: 650; margin: 4px 0 8px;}
.check.FAIL .state {color: #b42318;}
.check.NEEDS_REVIEW .state {color: #b54708;}
.check.PASS .state {color: #067647;}
.check .kv {display: flex; justify-content: space-between; font-size: 14px; padding: 3px 0; color: #475467;}
.check .kv b {font-weight: 600; color: #0f172a; font-variant-numeric: tabular-nums;}
.check .note {font-size: 12px; color: #98a2b3; margin-top: 6px;}

.clause {background: #fffdf7; border: 1px solid #eee6d3; border-radius: 14px; padding: 14px 18px; margin-bottom: 8px;
  font-family: Georgia, "Times New Roman", serif; font-size: 16px; line-height: 1.6; color: #1d2939;}
.clause .tag {font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-size: 11px; font-weight: 600;
  letter-spacing: 0.08em; color: #6b5a2e; background: #f6efdc; border-radius: 6px; padding: 2px 8px; margin-right: 8px;}
.calc {background: #0f172a; color: #e2e8f0; border-radius: 14px; padding: 14px 18px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 14px; line-height: 1.7;}
.calc .total {color: #fff; font-weight: 700; border-top: 1px solid #334155; margin-top: 6px; padding-top: 6px;}
.letter {background: #fff; border: 1px solid #eaecf0; border-radius: 12px; padding: 18px 22px; white-space: pre-wrap;
  font-family: Georgia, "Times New Roman", serif; font-size: 15px; line-height: 1.6; color: #1d2939;}
.done {background: #ecfdf3; border: 1px solid #abefc6; color: #054f31; border-radius: 14px; padding: 12px 16px; font-size: 15px;}
.empty {background: #fff; border: 1px dashed #d0d5dd; border-radius: 18px; padding: 36px; text-align: center; color: #475467;}
.empty code {background: #f2f4f7; padding: 2px 6px; border-radius: 6px;}

div[data-testid="stButton"] button, div[data-testid="stDownloadButton"] button {border-radius: 999px; font-weight: 500;}
div[data-testid="stButton"] button[kind="primary"] {background: #0f172a; border-color: #0f172a; padding: 10px 26px; font-size: 16px;}
div[data-testid="stExpander"] {border-radius: 14px; background: #fff;}
div[data-testid="stTable"] td, div[data-testid="stTable"] th {font-variant-numeric: tabular-nums;}
</style>
"""


def esc(x) -> str:
    return html.escape(str(x if x is not None else "—"))


def money(x):
    return f"${x:,.2f}"


def sec(text):
    st.markdown(f'<div class="sec">{esc(text)}</div>', unsafe_allow_html=True)


def load_results():
    rows = []
    for folder in ("discrepancy", "needs_review", "success"):
        for p in (DATA / "results" / folder).glob("*.json"):
            rows.append(json.loads(p.read_text()))
    return rows


def arrival_order() -> dict:
    """invoice -> when it was audited (audit log sequence), so the feed shows newest first."""
    order = {}
    for e in audit_log.read(DATA):
        if e.get("event") in ("checked", "needs_review") and e.get("invoice"):
            order.setdefault(e["invoice"], e["seq"])
    return order


def filter_rows(rows, status):
    """One status (PASS / FAIL / NEEDS_REVIEW), or "ALL"."""
    return rows if status in (None, "ALL") else [r for r in rows if r["status"] == status]


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


def model_badge(rows) -> str:
    """Which local model wrote the latest results (or that none was used)."""
    for r in sorted(rows, key=lambda r: -ARRIVAL.get(r["invoice"], 0)):
        for src in (r.get("terms_source"), r.get("written_by")):
            if src and src.startswith("model:"):
                return f"local model <b>{esc(src[6:].split(' ')[0])}</b>"
    env = os.environ.get("WATCHDOG_MODEL")
    return f"local model <b>{esc(env)}</b>" if env else "<b>rule-based</b> reader (no model)"


# ---------------------------------------------------------------- top of the page
def header(rows):
    ok, n, problem = audit_log.verify(DATA)
    chain = (f'<span class="badge ok">Audit log: <b>{n}</b> entries · chain intact</span>' if ok else
             f'<span class="badge bad">Audit log: {esc(problem)}</span>')
    st.markdown(f"""
<div class="top">
  <div>
    <div class="brand">Invoice Watchdog</div>
    <div class="tagline">Are we actually paying what we agreed to pay?</div>
    <div class="principle">AI understands · code verifies · humans authorize</div>
  </div>
  <div class="badges">
    <span class="badge">Runs on <b>Dell GB10</b> · {model_badge(rows)}</span>
    <span class="badge">Documents stay on this machine</span>
    {chain}
  </div>
</div>""", unsafe_allow_html=True)


def metrics(rows):
    fails = [r for r in rows if r["status"] == "FAIL"]
    review = [r for r in rows if r["status"] == "NEEDS_REVIEW"]
    tiles = [("risk", "At risk", money(sum(r["at_risk"] for r in fails))),
             ("", "Invoices audited", len(rows)), ("", "Discrepancies", len(fails)), ("", "Needs review", len(review))]
    st.markdown('<div class="metrics">' + "".join(
        f'<div class="tile {cls}"><div class="k">{k}</div><div class="v">{v}</div></div>' for cls, k, v in tiles)
        + "</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------- left: live feed
def reason(r) -> str:
    if r["status"] == "PASS":
        return "passed every check"
    return CHECK_NAMES.get(r.get("main_check") or "", "needs a person")


def feed(rows, selected):
    status = st.segmented_control("Show", list(FILTERS), format_func=lambda s: f"{FILTERS[s]} "
                                  f"({len(filter_rows(rows, s))})", default="ALL", key="filter",
                                  label_visibility="collapsed") or "ALL"
    shown = sorted(filter_rows(rows, status), key=lambda r: -ARRIVAL.get(r["invoice"], 0))
    if not shown:
        st.caption("No invoices match this filter.")
        return
    with st.container(height=640, border=False):
        for r in shown:
            amt = f'<span class="amt">{money(r["at_risk"])}</span>' if r["status"] == "FAIL" else ""
            done = " · approved" if r.get("approval") else ""
            st.markdown(f"""
<div class="card {r['status']}{' sel' if r['invoice'] == selected else ''}">
  <div class="row1"><span class="who"><span class="chip {r['status']}">{ICON[r['status']]} {LABEL[r['status']]}</span>{esc(r.get('vendor') or '?')}</span>{amt}</div>
  <div class="row2">{esc(r['invoice'])} · {esc(reason(r))}{done}</div>
</div>""", unsafe_allow_html=True)
            if st.button("Open evidence →", key=f"open-{r['invoice']}", type="tertiary"):
                st.session_state["selected"] = r["invoice"]
                st.rerun()


# ---------------------------------------------------------------- right: evidence
def check_card(name, status, pairs, note=""):
    rows = "".join(f'<div class="kv"><span>{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in pairs)
    note = f'<div class="note">{esc(note)}</div>' if note else ""
    status = status or "NEEDS_REVIEW"
    return (f'<div class="check {status}"><div class="name">{name}</div>'
            f'<div class="state">{ICON[status]} {LABEL[status]}</div>{rows}{note}</div>')


def checks(r):
    layers, lines = r.get("layers") or {}, r.get("lines") or []
    if not layers:
        return
    t, c, h = layers["transaction"], layers["commercial"], layers["historical"]
    tp, cp = [], []
    for l in lines:
        tp += [("PO price", money(l["po_price"]) if l["po_price"] is not None else "—"),
               ("Invoice price", f"{money(l['unit_price'])} / {l['unit']}")]
        if l["po_qty"] is not None:
            tp += [("Ordered · received", f"{l['po_qty']:g} · {l['received']:g}" if l["received"] is not None
                    else f"{l['po_qty']:g} · —")]
            if l["billed_before"]:
                tp += [("Already billed", f"{l['billed_before']:g}")]
            tp += [("Billed now", f"{l['qty']:g}")]
        cp += [("Invoice price", money(l["unit_price"])),
               ("Contract price", money(l["contract_price"])), ("Clause", l["contract_clause"])]
    if not lines and r.get("reasons"):
        tp, cp = [("", "not decided")], [("", "not decided")]
    prev = len(r.get("evidence", {}).get("previous_transactions", []))
    match = h.get("matched_transaction")
    hp = [("Duplicate of", match)] if match else [("Earlier invoices on this PO", prev)]
    multi = "" if len(lines) <= 1 else f"{len(lines)} lines"
    st.markdown('<div class="checks">'
                + check_card("Transaction · PO + receipt", t["status"], tp, multi)
                + check_card("Contract", c["status"], cp, multi)
                + check_card("History", h["status"], hp)
                + "</div>", unsafe_allow_html=True)


def verdict(r):
    if r["status"] == "FAIL":
        title = f"POTENTIAL LEAKAGE {money(r['at_risk'])} · {CHECK_NAMES.get(r['main_check'], r['main_check'])}"
    elif r["status"] == "NEEDS_REVIEW":
        title = f"A person must decide · {money(r['amount_under_review'] or r['total'])} under review"
    else:
        title = "Passed every check"
    st.markdown(f'<div class="who-line">{esc(r.get("vendor") or "?")} · {esc(r["invoice"])} · '
                f'PO {esc(r.get("po"))} · {esc(r.get("date"))} · total {money(r["total"])}</div>'
                f'<div class="verdict {r["status"]}"><div class="t">{esc(title)}</div>'
                f'<div class="s">{esc(r.get("explanation", ""))}</div></div>', unsafe_allow_html=True)
    if r["status"] == "NEEDS_REVIEW" and r.get("reasons"):
        sec("Why a person must decide")
        for x in r["reasons"]:
            st.markdown(f"- {x}")


def source_and_math(r):
    clauses = (r.get("evidence") or {}).get("clauses") or {}
    if clauses:
        sec("Source · the contract, word for word")
        st.markdown("".join(f'<div class="clause"><span class="tag">CLAUSE {esc(n)}</span>{esc(t)}</div>'
                            for n, t in clauses.items()), unsafe_allow_html=True)
    if r.get("calculation"):
        sec("Calculation")
        total = (f'<div class="total">At risk: {money(r["at_risk"])}</div>' if r["status"] == "FAIL" else "")
        st.markdown('<div class="calc">' + "".join(f"<div>{esc(c)}</div>" for c in r["calculation"])
                    + total + "</div>", unsafe_allow_html=True)


def invoice_as_received(r):
    sec("Invoice, as received")
    inv_json, inv_pdf = invoice_files(r)
    if inv_json:
        raw = json.loads(inv_json.read_text())
        rows, lines_sum = [], 0.0
        for l in raw.get("lines", []):
            qty, price = _num(l.get("qty")), _num(l.get("unit_price"))
            amt = (qty or 0) * (price or 0)
            lines_sum += amt
            rows.append({"SKU": l.get("sku") or "—", "Description": l.get("description") or "—",
                         "Qty": f"{qty:g}" if qty is not None else "—", "Unit": l.get("unit") or "—",
                         "Unit price": money(price) if price is not None else "—", "Amount": money(amt)})
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
    cols = st.columns(3)
    contract = DATA / r["evidence"]["contract"] if (r.get("evidence") or {}).get("contract") else None
    if inv_pdf:
        cols[0].download_button("View invoice PDF", inv_pdf.read_bytes(), inv_pdf.name, key=f"ip-{r['invoice']}")
    if inv_json:
        cols[1].download_button("View invoice JSON", inv_json.read_bytes(), inv_json.name, key=f"ij-{r['invoice']}")
    if contract and contract.exists():
        cols[2].download_button("View contract PDF", contract.read_bytes(), contract.name, key=f"c-{r['invoice']}")


def actions(r, approver):
    if r.get("dispute_draft"):
        with st.expander("Dispute draft (letter to the supplier)", expanded=False):
            st.markdown(f'<div class="letter">{esc(r["dispute_draft"])}</div>', unsafe_allow_html=True)
    approval = r.get("approval")
    if approval:
        text = (f"Approved by {approval['by']} at {approval['at']} — ready to send ({approval['outbox']}). "
                "Nothing was sent by the agent." if approval["decision"] == "dispute"
                else f"Checked and accepted by {approval['by']} at {approval['at']}.")
        st.markdown(f'<div class="done">✓ {esc(text)}</div>', unsafe_allow_html=True)
        return
    try:
        if r["status"] == "FAIL":
            if st.button("Approve dispute", type="primary", key=f"a-{r['invoice']}"):
                approve_dispute(r["invoice"], approver, DATA)
                st.rerun()
            st.caption("The agent drafted this. Only a person can release it.")
        elif r["status"] == "NEEDS_REVIEW":
            a, b = st.columns(2)
            if a.button("Mark correct", key=f"m-{r['invoice']}", use_container_width=True):
                mark_correct(r["invoice"], approver, DATA)
                st.rerun()
            if b.button("Send to dispute", key=f"d-{r['invoice']}", use_container_width=True):
                approve_dispute(r["invoice"], approver, DATA)
                st.rerun()
    except ApprovalError as exc:
        st.error(str(exc))


def evidence(r, approver):
    verdict(r)
    checks(r)
    source_and_math(r)
    sec("Decision")
    actions(r, approver)
    invoice_as_received(r)


def empty_state():
    st.markdown("""
<div class="empty">
  <div style="font-size:20px;font-weight:600;color:#0f172a;margin-bottom:8px">Waiting for invoices</div>
  <div>Start the agent with <code>python3 -m engine.pipeline --watch</code>,
  then let invoices arrive: <code>python3 scripts/drop_invoices.py data/demo/live</code></div>
  <div style="margin-top:6px">Or run everything at once: <code>python3 demo.py</code></div>
</div>""", unsafe_allow_html=True)


ARRIVAL: dict = {}


def main():
    global ARRIVAL
    st.set_page_config(page_title="Invoice Watchdog", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    with st.sidebar:
        approver = st.text_input("Your name (for approvals)", "AP reviewer")
        auto = st.toggle("Auto-refresh every 3 s", value=True)
        st.caption(f"latest audit hash: {audit_log.latest_hash(DATA)[:16]}…")

    @st.fragment(run_every=3 if auto else None)
    def body():
        global ARRIVAL
        ARRIVAL = arrival_order()
        rows = load_results()
        header(rows)
        metrics(rows)
        if not rows:
            empty_state()
            return
        by_id = {r["invoice"]: r for r in rows}
        selected = st.session_state.get("selected")
        if selected not in by_id:                 # default: the newest failure, else the newest invoice
            newest = sorted(rows, key=lambda r: (r["status"] != "FAIL", -ARRIVAL.get(r["invoice"], 0)))
            selected = st.session_state["selected"] = newest[0]["invoice"]
        left, right = st.columns([35, 65], gap="large")
        with left:
            feed(rows, selected)
            if st.button("Verify audit log", key="verify"):
                ok, n, problem = audit_log.verify(DATA)
                (st.success if ok else st.error)(f"{n} entries · chain intact · nothing was changed" if ok
                                                 else f"{n} entries · {problem}")
        with right:
            evidence(by_id[selected], approver)

    body()


main()
