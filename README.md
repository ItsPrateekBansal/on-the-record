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
3. **Audit engine** *(in progress)* — three layers, each check PASS, FAIL
   or NEEDS_REVIEW:
   - *Transaction:* invoice vs PO and goods receipt (price, quantity).
   - *Commercial:* invoice vs the **contract** (price, volume tiers, units
     per box). This catches invoices that match the PO perfectly but still
     break the agreement.
   - *Historical:* previous transactions in the company folder: invoices
     that over-bill a partly billed PO, and duplicates of paid invoices.
   AI reads the documents, Python makes every decision, and anything the
   contract doesn't define (e.g. "carton") goes to a person.
4. **Dispute drafter + dashboard + audit trail** *(in progress)* — a
   dispute email draft quoting invoice line vs. contract clause for every
   catch, a running $ saved counter, and a hash-chained audit trail.
   A human approves before anything is sent — the agent proposes, the
   human disposes.

## Run it

```bash
# Watch an inbox folder (drops a file in = an email arriving)
python3 watcher/inbox.py --dir ./data/inbox

# Screen-recordable end-to-end demo: watcher + parser, ~30 seconds
python3 demo_watch.py
```

## Demo data

```bash
pip install -r scripts/requirements.txt
python3 scripts/make_fake_data.py     # regenerates data/ and the answer key
python3 scripts/send_invoices.py data/demo/live   # emails PDFs into Mailpit
```

`data/expected_results.json` is the answer key: status, each layer, amount
at risk and the quoted clauses for every invoice. Live set: 4 failures,
$3,182 at risk, led by Bolt (PO match passes, contract check fails, $720).

## Test it

```bash
python3 watcher/test_inbox.py   # watcher: stability, retries, survival
python3 parser/test_parser.py   # parser: formats, warnings, integration
```

## Layout

```
watcher/inbox.py            AP inbox watcher (stdlib only)
watcher/test_inbox.py       watcher tests
parser/invoice_parser.py    invoice parser + validation
parser/test_parser.py       parser tests + watcher integration
demo_watch.py               runnable watcher + parser demo
render_video.py             renders demo output as a terminal video
demo/pipeline_demo.mp4      recorded demo (watcher + parser)
scripts/make_fake_data.py   demo data generator + answer key
scripts/send_invoices.py    emails demo invoices into Mailpit
data/                       demo invoices (PDF + JSON), companies/<vendor>/
                            (contract, POs, receipts, transactions), results/
INVOICE_WATCHDOG_PLAN.md    full build plan (v3)
```
