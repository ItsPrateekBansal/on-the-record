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
3. **Match engine** *(in progress)* — 3-way match against the PO and the
   contract rate card: duplicate invoices, prices above the contracted
   rate, quantity mismatches.
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
INVOICE_WATCHDOG_PLAN.md    full build plan
```
