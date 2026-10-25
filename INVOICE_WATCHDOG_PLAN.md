# Invoice Watchdog — Build Plan
**Dell x NVIDIA AI Hackathon · Sun Oct 25, 2026 · Frontier Tower, SF**
Prepared Oct 24 (Sat) night. Event: doors 08:30, kickoff 09:30, build 10:00–18:00, submissions close 18:00, top-8 demos 18:30, awards 20:00.

## The one-liner
Your AP department's night-shift auditor. An always-on, fully local AI agent that catches supplier overcharges and drafts the disputes — and no financial data ever leaves the box.

## Why this fits the judging criteria
- **Technical execution** — 3-way match engine (invoice vs PO vs contract), duplicate detection, local LLM dispute drafting, hash-chained audit trail. Real mechanisms, verifiable live.
- **Business value** — every flag is dollars: duplicates, price creep, quantity mismatch. The dashboard's running "$ saved" total makes the value countable in the demo itself.
- **Local-first design** — supplier invoices are financial data. Zero remote calls at runtime; everything on the GB10. The audit log itself stays on the box.
- **Demo quality** — one live moment: invoices stream in, the $ saved counter ticks up, a duplicate gets caught with invoice-line vs contract-clause evidence side by side, and a dispute draft appears for human approval.

## Architecture (all local)

```
 ┌──────────────────┐
 │ AP INBOX WATCHER │  mock mailbox folder; new invoice file = new arrival
 │ (folder watcher) │  (no real Gmail — no auth, no network, keeps local story intact)
 └────────┬─────────┘
          ▼
 ┌──────────────────┐
 │ INVOICE PARSER   │  structured JSON invoices: vendor, line items,
 │                  │  amounts, quantities, invoice no., date
 └────────┬─────────┘
          ▼
 ┌──────────────────┐
 │ MATCH ENGINE     │  checks each invoice against PO + contract rate card:
 │ (deterministic)  │  1. duplicate? (same vendor + invoice no., or same
 │                  │     vendor + amount + date within window)
 │                  │  2. price > contracted rate? (per line item)
 │                  │  3. quantity > PO quantity?
 └────────┬─────────┘
          ▼
 ┌──────────────────┐
 │ DISPUTE DRAFTER  │  local model (Qwen3-32B via Ollama) writes the dispute
 │ (local LLM)      │  email quoting invoice line vs contract clause as evidence
 └────────┬─────────┘
          ▼
 ┌──────────────────┐
 │ OUTBOX + APPROVAL│  drafts wait in outbox; HUMAN approves before anything
 │                  │  is "sent" (sent = moved to sent folder in demo)
 └────────┬─────────┘
          ▼
 ┌──────────────────┐
 │ DASHBOARD        │  running $ saved, catches by vendor, clean vs flagged,
 │ (one web page)   │  click any flag → evidence view (invoice line vs clause)
 └────────┬─────────┘
          ▼
 ┌──────────────────┐
 │ AUDIT TRAIL      │  every step logged to append-only hash-chained JSONL
 │ (Flight Recorder │  (invoice arrived → checks run → verdict → draft →
 │  layer)          │   approval). One command re-hashes to prove unedited.
 └──────────────────┘
```

**Scope guardrail:** structured invoice/PO/contract data (JSON), NOT receipt/invoice OCR. The product is the matching, the dispute draft, and the audit trail — not reading PDFs. One or two invoice images as garnish only if time remains.

## Mock data spec (generate first, ~20 invoices)
- **POs:** 4–5 POs across 3 vendors (e.g., Acme Office, Vertex Logistics, Nova Components) with quantities + contracted unit rates.
- **Contract rate card:** per-vendor, per-item rates + terms (e.g., "payment net-30, no partial overbilling").
- **Invoices (~20):** ~14 clean, ~6 planted violations:
  1. Exact duplicate (same invoice no. resubmitted)
  2. Near-duplicate (same vendor + amount + date, different invoice no.)
  3. Price above contracted rate (e.g., $120/unit vs $100 contracted)
  4. Quantity above PO (ordered 50, billed 65)
  5. Wrong vendor rate applied (another vendor's cheaper rate is not the issue — use: item billed at non-contract rate)
  6. One tricky clean case: same vendor + same amount, different PO — must NOT flag (shows precision, judges love this)
- Each invoice: id, vendor, date, PO ref, line items (sku, qty, unit price, amount), total.

## Sunday hour-by-hour (10:00–18:00)
| Time | Block | Done when |
|---|---|---|
| 10:00–10:30 | Setup: model check (`ollama list`, test prompt), repo scaffold, mock data in place | Local model responds; mock invoices load |
| 10:30–12:00 | Inbox watcher + parser + match engine (the 3 checks) | All 6 planted violations flagged; tricky clean case NOT flagged |
| 12:00–13:00 | Dispute drafter (local LLM) + outbox + approval flow | Each flag produces a draft quoting invoice line + contract clause |
| 13:00–13:30 | Lunch (provided) | — |
| 13:30–14:30 | Dashboard (one page: $ saved, catches by vendor, clean vs flagged, evidence view) | Counter ticks live as invoices process |
| 14:30–15:30 | Audit trail (hash-chained JSONL) + verify command | Re-hash proves log unedited; every step traceable |
| 15:30–16:30 | End-to-end dry run at demo speed, bugfix | Full loop green twice in a row |
| 16:30–17:30 | Harden + record backup video + submission | Backup video on disk, submission in |
| 17:30–18:00 | Buffer / pitch rehearsal | — |

**Timebox rule:** if NemoClaw/OpenClaw fights you for more than 30 min at 10:00, drop it — build the agent loop in plain Python. The match engine, drafts, dashboard, and audit trail are the product, not the framework. Same for the LLM: if generation is slow, use template drafts with the evidence filled in, and let the LLM polish only the demo-case draft.

## Team split (adjust to your size)
- **Person A:** watcher + parser + match engine
- **Person B:** dispute drafter + dashboard
- **Person C:** audit trail + mock data + demo/pitch
- Solo/duo: cut the dashboard to one static-refresh page and the audit trail to the JSONL + verify command; the match engine + drafts are non-negotiable.

## Demo script (90 seconds)
1. "It's 2 AM. Invoices are arriving in the AP inbox." Start the stream — invoices appear, dashboard counter starts.
2. "Watch the $ saved counter." A duplicate gets caught (invoice no. matches an earlier one) — flag with evidence.
3. A price-creep invoice: $120/unit vs $100 contracted — flag, dispute draft appears quoting the contract clause.
4. "A human approves before anything is sent." Click approve on one draft → moves to sent.
5. Closer: "And every step is provable." One command re-hashes the audit log — nothing edited after the fact. Final frame: total $ saved.

## Tonight checklist (minimal — sleep matters, train is 6:56 AM)
- [x] Models: Nemotron-3-Super + Qwen3-32B pulled via Ollama (verify: `ollama list`)
- [ ] Copy `~/.ollama/models` to the 2 TB disk
- [ ] Scaffold repo filenames only: `watcher/inbox.py`, `parser/invoice.py`, `engine/match.py`, `drafter/dispute.py`, `dashboard/app.py`, `audit/event_log.py`, `data/pos.json`, `data/contracts.json`, `data/invoices/`
- [ ] Slack app token only if you want flagged invoices pushed to Slack too (optional — dashboard is the demo surface)

## Sunday logistics (recap)
- Caltrain 601, San Jose Diridon 6:56 AM → SF 4th & King 8:16 AM, Muni to Civic Center → ~8:45 at 995 Market St. Backups 603 (7:26→8:46), 605 (7:56→9:16). Diridon construction: check track boards.
- Driving alternative: leave by ~7:15, ~50–65 min, SF meters free Sundays.
- Bring: laptop + charger, 2 TB disk with models, USB-C adapters. GB10 loaner at venue; demo runs on it.
