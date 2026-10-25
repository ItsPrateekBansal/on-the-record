# Invoice Watchdog

Your AP department's night-shift auditor. An always-on, fully local AI
agent that catches supplier overcharges and drafts the disputes — and no
financial data ever leaves the box.

Built at the Dell x NVIDIA AI Hackathon (BuilderBase), Sunday Oct 25, 2026,
for the Dell Pro Max with GB10. Fully local by design: no remote LLM calls
at runtime.

## How it works

1. **Watcher** — watches the AP inbox folder around the clock. A new
   invoice file is dispatched only once its size is stable, so partial
   writes are never parsed. Bad files are reported once and retried only
   when they change — a bad file can never kill the watcher.
2. **Parser** — validates and normalizes each invoice (vendor, invoice
   number, PO, total, line items). Tolerates messy real-world formats
   (`"$7,800.00"`, string quantities, aliased keys) and warns instead of
   failing on a missing total or a total that doesn't match its lines.
3. **Audit engine** — loads the company, its whole contract, the PO, the
   goods receipt and previous transactions, then runs three layers, each check PASS, FAIL
   or NEEDS_REVIEW:
   - *Transaction:* invoice vs PO and goods receipt (price, quantity).
   - *Commercial:* invoice vs the **contract** (price, volume tiers, units
     per box). This catches invoices that match the PO perfectly but still
     break the agreement.
   - *Historical:* previous transactions in the company folder: invoices
     that over-bill a partly billed PO, and duplicates of paid invoices.
   AI reads the documents, Python makes every decision, and anything the
   contract doesn't define (e.g. "carton") goes to a person.
4. **Report** — every invoice is saved to its company's `transactions/`,
   the verdict goes to `results/success|discrepancy|needs_review/`, a short
   alert (no prices) to `alerts.jsonl`, and every step to a hash-chained
   audit log. Explanations and dispute drafts are templates for now; the
   local model (Nemotron / Qwen) will rewrite them later.
5. **Dashboard + approval** — the evidence screen: PO check next to the
   contract check, the clause quoted, the math, the dispute draft. Only a
   person clicking Approve moves a dispute to `outbox/`, "ready to send";
   nothing is ever sent by the agent.

## Run it

```bash
pip install -r requirements.txt             # only for the dashboard, PDFs and the data generator

python3 -m engine.pipeline --watch          # terminal 1: audits invoices as they land in data/inbox/
streamlit run dashboard/app.py              # terminal 2: evidence screen + Approve
python3 scripts/drop_invoices.py data/demo/live   # terminal 3: invoices "arrive" one by one

python3 scripts/reset_demo.py               # before every demo run: back to a clean state
```

`--once` audits what is in the inbox and stops.

**Local model (Nemotron 3 Super / Qwen 32B):** `export WATCHDOG_MODEL=<name from ollama list>`
or `--model <name>`. The model then reads PDF invoices and the whole contract and rewrites the
explanation and dispute draft. Python checks every value it returns against the documents and
keeps a rewrite only if every amount and clause number is unchanged. Without a model: JSON
invoices, rule-based contract reading, template text. `python3 -m engine.llm <name>` tests a
model; `--selftest --model <name>` runs all 20 demo PDFs through it.

**NemoClaw / OpenClaw:** skills in `skills/` (`audit-invoices`, `daily-summary`); the agent
posts the queued alerts from `python3 -m engine.alerts pending`. Setup: `docs/NEMOCLAW_SETUP.md`.

## Demo data

```bash
python3 scripts/make_fake_data.py     # regenerates data/ and the answer key
python3 scripts/drop_invoices.py data/demo/live   # invoices "arrive" in data/inbox/
```

`data/expected_results.json` is the answer key: status, each layer, amount
at risk and the quoted clauses for every invoice. Live set: 4 failures,
$3,182 at risk, led by Bolt (PO match passes, contract check fails, $720).

## Test it

```bash
python3 watcher/test_inbox.py   # watcher: stability, retries, survival
python3 parser/test_parser.py   # parser: formats, warnings, integration
python3 engine/test_evidence.py # load company, contract, evidence
python3 engine/test_pipeline.py # checks, reporting, audit log, approval
python3 -m engine.pipeline --selftest   # all 20 demo invoices vs the answer key
```

## Layout

```
watcher/inbox.py            AP inbox watcher (stdlib only)
watcher/test_inbox.py       watcher tests
parser/invoice_parser.py    invoice parser + validation
parser/test_parser.py       parser tests + watcher integration
parser/extract.py           PDF -> JSON with the local model (Ollama)
engine/evidence.py          steps 4-6: company, contract terms, PO, receipt, history
engine/checks.py            step 7: the three layers (plain Python)
engine/report.py            steps 8-11: transactions, results, explanation, alert
engine/audit_log.py         hash-chained audit log + verify
engine/approval.py          step 13: approve dispute / mark correct
engine/pipeline.py          runs it all: --watch, --once, --selftest
engine/llm.py               local model via Ollama (Nemotron / Qwen), test with python3 -m engine.llm
engine/alerts.py            alert queue + morning summary for the OpenClaw agent
skills/                     OpenClaw skills: audit-invoices, daily-summary
docs/NEMOCLAW_SETUP.md      connecting the models and NemoClaw on the GB10
dashboard/app.py            step 12: Streamlit evidence screen
demo_watch.py               runnable watcher + parser demo
render_video.py             renders demo output as a terminal video
demo/pipeline_demo.mp4      recorded demo (watcher + parser)
scripts/make_fake_data.py   demo data generator + answer key
scripts/drop_invoices.py    drops demo invoices into the inbox, one by one
scripts/reset_demo.py       clears results, logs and audited transactions
data/                       demo invoices (PDF + JSON), companies/<vendor>/
                            (contract, POs, receipts, transactions), results/
```
