# Invoice Watchdog — Hackathon Build Plan (v3)

As of Oct 25, 2026 · Repositioned as a contract-aware AP audit agent · Team of 3

---

## The one sentence we must prove

> "The invoice matched the PO perfectly. Our local agent still caught a $720 contract overcharge, showed the clause, waited for human approval, and could not leak the invoice."

**Product question:** "Are we actually paying what we agreed to pay?"

**Design philosophy:** AI understands. Code verifies. Humans authorize.

---

## Part 0: Read this first

**Event:** Sunday, Oct 25, 2026, Frontier Tower, San Francisco. Hardware: Dell Pro Max with GB10. Stack: NemoClaw, OpenClaw, OpenShell. Channel: Slack. Judged on technical execution, business value, local-first design, demo quality.

**Schedule (latest listing, confirm at check-in):**

| Time | What |
| --- | --- |
| 8:30 | Doors open, team formation |
| 9:30 | Kickoff |
| 10:00 | Build sprint starts |
| 18:00 | Build ends, **submissions due** |
| 18:30 | Demos begin |

This means: **code freeze at 17:00**, submission ready by 17:45, pitch practice after submitting.

**Check the rules at check-in.** Ask the organizers if code and data written before the event are allowed. The fake data set and the scripts already exist; if pre-written code isn't allowed, regenerate them during the event.

---

## Part 1: Positioning — what we are and are not

**Do not sell this as three-way matching.** ERPs such as Oracle already do PO matching, receipt matching, tolerances, duplicate checks and invoice holds. If we pitch "AI invoice matching," the judges' first thought is "my ERP does that."

| Traditional ERP matching | Invoice Watchdog |
| --- | --- |
| Does the invoice agree with the PO and the receipt? | Does the transaction comply with the **contract** behind it? |
| Structured records only | Reads plain-language contracts: prices, volume tiers, units per box, effective dates |
| Waits for someone to run it | An agent that wakes up, gathers the evidence and investigates by itself |

**One-paragraph pitch:**

> Invoice Watchdog is a local, autonomous AP audit agent that continuously investigates supplier invoices against transactional records, commercial agreements and payment history. Unlike traditional matching, which checks whether an invoice agrees with procurement records, Watchdog catches cases where the invoice and the PO agree but both violate the underlying contract. A local AI model interprets the contract, deterministic code verifies every discrepancy, OpenShell keeps the data from leaking, and every action is evidence-backed and human-approved.

We **do** have PO, receipt and invoice data, so the transaction layer is genuine three-way matching. We show it as one layer of the audit, never as the innovation.

---

## Part 2: How an audit works

### 2.1 Three layers, three outcomes

Every invoice goes through three layers. Each check returns **PASS**, **FAIL** or **NEEDS_REVIEW**.

| Layer | Checks | Source |
| --- | --- | --- |
| A. Transaction | `po_price`, `po_quantity`, `receipt_quantity` | `reference/pos/`, `reference/receipts/` |
| B. Commercial | `contract_price` (with volume tiers and unit conversion) | `reference/contracts/` |
| C. Historical | `duplicate` (same vendor, same PO, same amount as a paid invoice) | `reference/paid_invoices.json` |

**Invoice status:** FAIL if any check fails; otherwise NEEDS_REVIEW if any check could not be decided; otherwise PASS.

**Amount at risk** (one formula, no double counting):

- Duplicate: the whole invoice total.
- Otherwise: invoice total − payable, where payable = Σ min(billed qty, PO qty, received qty) × min(billed price, contract price), all in contract units.
- NEEDS_REVIEW: $0 at risk; the invoice total is shown as "under review."

**NEEDS_REVIEW is a feature.** If the contract doesn't define a unit the invoice uses (for example "carton"), the system must not guess. It says so and hands the invoice to a person.

### 2.2 The agent investigates (no one uploads documents)

When an invoice arrives, the agent gathers its own evidence:

```
New invoice in data/inbox/
  → extract supplier, invoice number, PO number, SKUs, quantities, units, prices   (local model)
  → find the PO:        reference/pos/<PO>.json
  → find the receipt:   reference/receipts/ (match on po_number)
  → find the contract:  reference/contracts/index.json → vendor → contract file and SKU clause
  → find the clause:    plain text search in <vendor>_contract.txt, then the model picks from the found lines
  → find history:       reference/paid_invoices.json (same vendor)
  → extract commercial terms from the clause   (local model → Pydantic)
  → run the deterministic checks               (Python)
  → write the evidence package + audit log entry
  → Slack alert (short), dashboard (full evidence)
```

### 2.3 The trust chain

```
AI interprets → Pydantic validates → Python decides → AI explains → human approves
```

1. **Local model extracts** facts as JSON (invoice fields, contract price, units per box, clause number, clause text).
2. **Pydantic validates**: required fields present, prices and quantities numeric, dates valid, SKU and clause present. Invalid output gets 1 retry, then the invoice becomes NEEDS_REVIEW. It never proceeds silently.
3. **Python decides** PASS/FAIL and computes the dollar amount. The model never decides whether 13.44 is bigger than 12.00.
4. **The model explains** the verified result and drafts the dispute, quoting the clause.
5. **A person approves.** Only the Approve button moves a draft into `outbox/`.

**Answer key:** `data/expected_results.json` holds the right result for every invoice (status, each layer, amount, clauses). Build `python -m watchdog selftest` early: it scans the demo invoices and compares them against this file. Every code change must keep the selftest green.

---

## Part 3: The data set (ready: `scripts/make_fake_data.py`)

Regenerate any time with `.venv/bin/python scripts/make_fake_data.py`. The script recomputes every expected result from the POs, receipts and contracts, and stops if its own answer key disagrees.

### 3.1 Live demo (4 invoices, sent by email during the pitch)

| # | Supplier | Scenario | Transaction | Contract | History | At risk | Shows |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **Bolt Industrial** | 500 × $13.44. **PO-7750 also says $13.44.** Contract 3.1 says $12.00 | PASS | **FAIL** | PASS | **$720** | **The differentiator:** PO match passes, contract fails |
| 2 | Acme Packaging | INV-1043A: same vendor, PO and $2,400 as paid INV-1043 | PASS | PASS | **FAIL** | $2,400 | Historical intelligence |
| 3 | Coastal Supply | Billed 100 pallets; PO-7781 ordered 80; receipt GR-4432 received 80 | **FAIL** | PASS | PASS | $1,200 | Ordinary matching, as a baseline |
| 4 | Delta Office | Everything correct | PASS | PASS | PASS | $0 | Clean invoices pass |

**Live total: 3 failed, $4,320 at risk.** Files are numbered so Bolt arrives first.

### 3.2 Wifi-off demo (1 invoice)

| # | Supplier | Scenario | At risk | Shows |
| --- | --- | --- | --- | --- |
| 5 | Evergreen Parts | 10 boxes at $150. Clause 2.4: $11.50 per unit, boxes of 12, so at most $138 per box | $120 | Contract understanding + unit conversion + Python math |

Bolt shows **contract price retrieval**. Evergreen shows **semantic interpretation and unit normalization**. Present them as two separate capabilities.

### 3.3 Overnight batch (14 invoices, for the morning summary)

11 pass, 2 fail, 1 needs review:

- **INV-CS-0897** (Coastal): $64.80 per pallet vs clause 4.1 $60.00 → $600
- **INV-1051** (Acme): 400 rolls billed, PO ordered 200 → $680
- **INV-EV-199** (Evergreen): 4 **cartons** of grease at $93.60. The contract prices tubes and never defines a carton → **NEEDS_REVIEW**, $374.40 under review, not called an overcharge
- **INV-EV-201** (Evergreen): $138 per box of 12, which is exactly correct, so it shows that correct box pricing passes

**Morning summary:** "Audited 14 invoices overnight. 2 failed, $1,280 at risk. 1 needs human review ($374.40)."

### 3.4 Files

```
data/
├── demo/live/                01_bolt … 04_delta (PDF)
├── demo/wifi_off/            05_evergreen_INV-EV-208.pdf
├── demo/overnight/           o01 … o14 (PDF)
├── reference/pos/            PO-*.json        (25 POs)
├── reference/receipts/       GR-*.json        (one per PO; GR-4432 = Coastal)
├── reference/contracts/      <vendor>_contract.pdf/.txt + index.json (vendor → file, dates, SKU → clause)
├── reference/paid/           6 paid invoice PDFs
├── reference/paid_invoices.json
├── reference/vendors.json
├── expected_results.json     the answer key (status, layers, at_risk, evidence, clause text)
├── inbox/                    new invoices land here
└── outbox/                   ONLY human-approved disputes
```

**Optional switch:** in `make_fake_data.py`, set Coastal's receipt to 75 (`RECEIPT_OVERRIDES`) to show "ordered 80, received 75, billed 100." Its amount becomes $1,500 and the live total $4,620. Update its `expect` line too. Only do this if the receipt layer is built.

---

## Part 4: Architecture — one pipeline, one shared folder

```
                   SUPPLIER
                       │ invoice email
                       ▼
                    MAILPIT  (GB10 host)
                       │ fetcher: python -m watchdog fetch
                       ▼
                 data/inbox/
                       │
              OPENCLAW HEARTBEAT (inside OpenShell)
                       │ skill audit-invoices → python -m watchdog scan
                       ▼
            AUTONOMOUS INVESTIGATION
          ┌────────────┼────────────┐
          ▼            ▼            ▼
     PO + RECEIPT   CONTRACT      HISTORY
          └────────────┼────────────┘
                       ▼
               LOCAL MODEL (GB10)  extract facts
                       ▼
                 PYDANTIC GATE
                       ▼
              DETERMINISTIC PYTHON
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   Transaction     Commercial      Historical
        └──────────────┼──────────────┘
                       ▼
        EVIDENCE PACKAGE + HASH-CHAINED LOG (SQLite)
             ┌─────────┴─────────┐
             ▼                   ▼
      SLACK (short alert)   STREAMLIT (evidence + draft)
                                  ▼
                           HUMAN APPROVAL
                                  ▼
                        outbox/  "ready to send"
```

**Why this shape:** host services like Mailpit may not be reachable from inside the OpenShell sandbox. So the sandbox never talks to Mailpit. A small fetcher on the host moves attachments into the shared folder, and the agent only reads that folder.

**Decide in the first hour (preflight, Part 10):**

- **Plan A:** the skill runs the tool inside the sandbox, and the data folder is shared with the host.
- **Plan B:** if sharing a folder is hard, run the tool as a tiny local web service on the host and allow only that address in the sandbox policy. Ask the NVIDIA mentors.

**The approval boundary (never blur this):** the agent can detect, investigate, calculate, explain, draft and alert. It **cannot send**. It has no email access, and its network policy allows only Slack and the local model. In the demo we say "ready to send," never "sent."

**Privacy rule:** Slack gets only supplier, amount and problem type. Contract prices, clause text and dispute drafts stay on the local dashboard.

**Don't add:** Kafka, Kubernetes, vector databases, multiple agents, cloud services, RAG frameworks. With five contracts, `index.json` plus plain text search is enough. The sophistication is in the workflow, not the number of tools.

**Repo layout (`on-the-record`):**

```
watcher/inbox.py          done: watches data/inbox/, dispatches stable .json files
parser/invoice_parser.py  done: validates invoices; Line.unit carries "box (12)", "carton"
engine/                   B: retrieval + the three layers (port audit() from scripts/make_fake_data.py)
drafter/                  B: explanation + dispute draft (local model)
dashboard/app.py          C: evidence screen, Approve, Verify
audit/                    C: hash-chained log
skills/                   A: audit-invoices, daily-summary (SKILL.md)
scripts/                  make_fake_data.py, send_invoices.py
data/                     demo invoices (PDF + JSON twin), reference/, expected_results.json
```

The watcher reads `.json` today. Until PDF extraction with the local model works, drop the JSON twins from `data/demo/` into `data/inbox/`; the rest of the pipeline is the same.

---

## Part 5: Who does what (3 people)

| Person | Role | Owns |
| --- | --- | --- |
| **A** | Platform + security | NemoClaw/OpenClaw/OpenShell install, Ollama, Slack, network policy, heartbeat, `audit-invoices` and `daily-summary` skills, Mailpit + `watchdog fetch`, **blocked-egress demo**, **wifi-off run** |
| **B** | Brain | `watchdog scan`: extraction (model → Pydantic + 1 retry), evidence retrieval (PO, receipt, contract clause, history), the three layers of checks, unit conversion, NEEDS_REVIEW path, explanations and dispute drafts, `watchdog selftest` |
| **C** | Screens + story | Streamlit evidence screen, Approve button, hash-chained audit log + Verify, morning summary numbers, then **pitch, demo script, backup video, README, submission** |

**Already done (no one needs to build these):** the fake data set, the answer key, and `scripts/send_invoices.py` (emails PDFs into Mailpit).

**Handoffs:**

- B → C by 12:00: the result row format (copy the fields of `expected_results.json`, so C can build the screen from that file before `scan` works).
- B → A by 13:00: `python -m watchdog scan` runs from the command line, so A can wrap it in a skill.
- C starts the pitch work at 15:00 at the latest, even if the screens aren't perfect.

**Cut first if behind:** Telegram (stretch only), the receipt layer details, the optional 75-received switch, the `show-catch` skill.

---

## Part 6: The evidence screen (the most important screen)

Don't make the dashboard an invoice table. The judge should understand the whole product from one screen:

```
BOLT INDUSTRIAL SUPPLY LLC · INV-B-5520            POTENTIAL LEAKAGE: $720.00

TRANSACTION CHECK                     CONTRACT CHECK
PO price        $13.44                Invoice price   $13.44
Invoice price   $13.44                Contract price  $12.00
Status          ✓ PASS                Status          ✕ FAIL

SOURCE: Contract clause 3.1
"Unit price for SKU BX-200 shall be $12.00 per unit, fixed through Dec 31, 2026."

CALCULATION
($13.44 − $12.00) × 500 = $720.00

RECOMMENDED ACTION: request supplier correction
[View invoice]  [View contract]  [Approve dispute]
```

The clause text comes from `evidence.clauses` in the result, quoted word for word. NEEDS_REVIEW invoices get their own card: the reason, the unclear term ("carton"), the clause, and the buttons [Mark correct] / [Dispute].

---

## Part 7: What to study before 10:00

**Everyone (20 min):** this plan's Parts 1–3, and the [NemoClaw Quickstart](https://docs.nvidia.com/nemoclaw/latest/get-started/quickstart.html).

**Person A:** NemoClaw Quickstart and its DGX Spark guide (GB10 is the same chip); the [GB10 install guide](https://ai-muninn.com/en/blog/nemoclaw-install-gx10-from-scratch) (third-party: Node 22, harmless exit code 243, `sudo npm link`, the cgroup v2 Docker fix, OpenShell aarch64 tar.gz); OpenClaw skills (`SKILL.md`) and heartbeat/cron; OpenShell policy tiers and `nemoclaw <name> policy add`; sharing a folder with the sandbox; Slack Socket Mode; Mailpit (SMTP 1025, web 8025).

**Person B:** pdfplumber; Pydantic models for `Invoice`, `LineItem`, `ContractTerm`, `CheckResult`; asking Ollama for JSON and validating it; read `make_fake_data.py`'s `audit()` function: it is the reference logic for `checks.py`.

**Person C:** Streamlit (columns, metrics, buttons, auto-refresh); `sqlite3`; hash chains; the demo script in Part 12.

---

## Part 8: What is already installed (Ananya's laptop)

| Item | Status |
| --- | --- |
| Homebrew, Docker 28.4, Node 24, Python, uv, Git | Already there |
| Ollama + `qwen3.5:9b` (7.6 GB) | Installed, tested, for practice only |
| Project folder `~/Desktop/invoice-watchdog` with Python 3.12 venv and 9 packages | Done |
| Fake data set v3 + answer key | Done |
| ARM64 Linux packages for the GB10, `wheels-gb10-aarch64/` (125 MB) | Done |
| Mailpit image for ARM64, `mailpit-arm64.tar` (13 MB) | Done |

**Finding from the laptop test:** with `qwen3.5:9b`, Ollama's strict JSON `format` option returns "structured output is unavailable." A plain "return only JSON" prompt worked. So the code must not depend on `format`. Use prompt + Pydantic check + 1 retry, and test `format` again on the GB10 models.

**Laptop limits:** 16 GB memory, about 37 GB free disk. Nemotron Super and Qwen 32B can't run here; they are for the GB10. Copy them to the SSD from whichever teammate has them.

---

## Part 9: NemoClaw setup

- Messaging channels must be enabled **during onboarding, before the first sandbox is built**. Have the Slack tokens ready before onboarding. (Telegram is optional; enable it at onboarding only if the token is ready, because adding it later needs a rebuild.)
- A policy tier is not enough on its own: Slack needs its **policy preset / endpoint**, added during onboarding or with `nemoclaw <name> policy add`.
- A scripted install must **explicitly accept third-party software**.

**Interactive install (recommended):**

```bash
export NEMOCLAW_DISABLE_TELEMETRY=1
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_APP_TOKEN=xapp-...
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
nemoclaw onboard
```

During `nemoclaw onboard`: agent **OpenClaw**, provider **Ollama** (local), enable **Slack**, tier **Restricted**, only the Slack endpoint added. No web search, no extra presets.

**Scripted install (if over SSH or onboarding stalls):**

```bash
curl -fsSL https://www.nvidia.com/nemoclaw.sh | \
  NEMOCLAW_NON_INTERACTIVE=1 \
  NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 \
  NEMOCLAW_AGENT=openclaw \
  NEMOCLAW_PROVIDER=ollama \
  NEMOCLAW_SANDBOX_NAME=watchdog \
  bash
```

**Check:** `nemoclaw watchdog status` (expect Ready), `nemoclaw watchdog logs --follow`, then say "hi" to the bot in `#ap-watchdog`.

**Mailpit on the GB10 host:**

```bash
docker load -i mailpit-arm64.tar
docker run -d --name mailpit -p 8025:8025 -p 1025:1025 axllent/mailpit
```

---

## Part 10: Preflight test (first hour on the GB10, A + B)

Test each model; don't trust docs:

| Test | Pass means | Super | Qwen 32B |
| --- | --- | --- | --- |
| Model loads | `ollama run <model> "hi"` answers | | |
| Structured JSON | `format` works, or prompt + Pydantic passes 5 out of 5 | | |
| Bolt invoice extracts | 500 units at $13.44, PO-7750 | | |
| Bolt clause quoted | Clause 3.1 word for word, $12.00 per unit | | |
| Evergreen boxes | Clause 2.4 → $11.50 per unit, 12 per box | | |
| Carton case | Says "carton" is not defined (does not invent a number) | | |
| Fast enough | One invoice end to end in under 20 seconds | | |

Plumbing:

| Test | Pass means |
| --- | --- |
| Sandbox reaches model | The skill gets an answer from Ollama |
| Sandbox reaches data | The skill runs `python -m watchdog scan` and reads `data/inbox/` |
| Dashboard reaches results | The dashboard sees rows the skill wrote |
| Mailpit to inbox | An email sent to Mailpit appears as a PDF in `data/inbox/` |
| Heartbeat | The agent runs the skill by itself within 1 minute |
| Egress blocked | A request to a public website from the sandbox is refused |

**Pick the model** that passes everything. Prefer Nemotron Super (NVIDIA's own model is a good story for these judges) if it is fast enough. Load one model at a time (`OLLAMA_MAX_LOADED_MODELS=1`).

---

## Part 11: Build schedule (10:00 to 18:00)

| Time | A (Platform) | B (Brain) | C (Screens + story) | Checkpoint |
| --- | --- | --- | --- | --- |
| 10:00–11:00 | NemoClaw + Slack, policy, Mailpit | Model preflight | SQLite tables, dashboard shell reading `expected_results.json` | Model chosen, bot says hi |
| 11:00–13:00 | `watchdog fetch`, skill runs `scan`, Slack alert | Extraction + Pydantic, retrieval, 3 layers, `selftest` | Evidence screen for Bolt, audit log | `selftest` on the 4 live invoices: Bolt contract FAIL with PO PASS, $4,320 total |
| 13:00–15:00 | Blocked-egress demo | NEEDS_REVIEW path, dispute drafts | Approve → outbox, Verify button, review card | Layer 1 end to end |
| 15:00–16:30 | Heartbeat, `daily-summary` skill | Evergreen boxes, overnight selftest (14) | Pitch + demo script, first full practice | Email → Slack alert with nobody typing; summary "2 failed, $1,280, 1 review" |
| 16:30–17:00 | Wifi-off run | Bug fixes | Backup video recording | Evergreen caught at $120 with wifi off |
| 17:00 | **Code freeze.** Only bug fixes. | | | |
| 17:00–17:45 | 3 full demo runs together, README, submission | | | Submitted by 17:45 |
| 18:00–18:30 | Practice the pitch out loud twice | | | |

If something blocks you for more than 30 minutes, ask a mentor right away.

---

## Part 12: The demo script (about 3 minutes)

1. **Problem (15 s):** "Companies pay thousands of invoices. Their ERP checks that the invoice matches the PO. Nobody checks that the PO matches the contract."
2. **Overnight (15 s):** the morning Slack summary: "Audited 14 invoices overnight. 2 failed, $1,280 at risk. 1 needs human review." Nobody asked it to.
3. **Live (30 s):** email the 4 live invoices to Mailpit. The agent picks them up by itself. Three alerts appear; the clean one passes.
4. **The wow, Bolt (40 s):** open the evidence screen. "The invoice matches the PO perfectly: PASS. But Watchdog checks the agreement behind the transaction." Contract FAIL, clause 3.1 quoted, $720.
5. **History + baseline (15 s):** Acme, a near-duplicate of a paid invoice, $2,400. Coastal, ordinary over-billing, $1,200: "we do the normal checks too."
6. **Honest uncertainty (10 s):** the carton invoice: "The contract doesn't define a carton, so it asks a person instead of guessing."
7. **Human approval (15 s):** "AI investigates. Code verifies. Humans authorize." Click Approve; the dispute moves to the outbox, ready to send. The agent sent nothing.
8. **Cannot leak (20 s):** in Slack, ask the agent to upload the invoice to a public site. OpenShell blocks it.
9. **Wifi off (15 s):** wifi off, send Evergreen. Caught: $150 per box vs $138 from clause 2.4, $120. The Slack alert waits until wifi is back; the dashboard shows it now.
10. **Audit trail (5 s):** click Verify on the tamper-evident log.
11. **Business (10 s):** "1,000 invoices a month at $2,000 each is $2M. Even 1% leakage is $20,000 a month." (Illustrative numbers; say so if asked.)
12. **Closing line:** the one sentence at the top of this plan.

**About the audit trail:** call it **tamper-evident**, never tamper-proof. The hash chain shows if a past entry was changed; it can't stop a full rewrite. Posting the latest hash in the daily Slack summary means a rewrite would no longer match what was already posted. Add the hash to the summary to make that true.

---

## Part 13: Every technology has a job

| Technology | Its job in the story |
| --- | --- |
| Dell Pro Max + GB10 | Runs document intelligence locally; contracts and prices never leave the machine |
| Local NVIDIA model via Ollama | Reads invoices and contract language, turns them into structured evidence |
| OpenClaw | The autonomous auditor: wakes up, investigates, gathers evidence, calls tools |
| NemoClaw | Deploys the OpenClaw agent with the local model and the sandbox |
| OpenShell | Enforces the network boundary; blocks exfiltration (shown live) |
| Pydantic | Validates AI output before it reaches financial logic |
| Python | Makes every financial decision and does every calculation |
| SQLite + hash chain | Local, tamper-evident audit history |
| Mailpit | Real email intake, simulated suppliers |
| Slack | Surfaces only exceptions; finance doesn't watch another dashboard |
| Streamlit | Evidence, explanation, dispute draft, human approval |

---

## Part 14: How we cover each judging point

| Judged on | What shows it |
| --- | --- |
| Technical execution | Autonomous agent in an OpenShell sandbox, evidence retrieval, local model reading contracts, Pydantic gate, deterministic checks, NEEDS_REVIEW path, tamper-evident log, selftest against an answer key |
| Business value | Catches what ERPs miss (PO-matched but off-contract), clear dollar amounts, human approval, share-of-savings pricing |
| Local-first design | Model on the GB10, local mail server and data, blocked upload, wifi-off run, Slack gets only short alerts |
| Demo quality | Bolt "PASS then FAIL" moment, judges can count the catches, numbers add up, backup video |

---

## Part 15: Risks and plan B

| Problem | Plan B |
| --- | --- |
| NemoClaw won't install in 45 min | Ask NVIDIA mentors. Keep building `watchdog` and the dashboard outside the sandbox. |
| Skill can't reach the shared folder | Plan B from Part 4 (local web service allowed in policy). |
| Strict JSON `format` fails | Prompt + Pydantic + 1 retry. Still bad → NEEDS_REVIEW, never crash. |
| Model invents a carton size | Python only accepts conversions found in the clause text; otherwise NEEDS_REVIEW. |
| Clause not quoted word for word | Find the clause by text search first, then let the model pick from the found lines. |
| Model too slow | Faster model from preflight. |
| Mailpit fetch breaks | Drop PDFs straight into `data/inbox/`; the agent still picks them up. |
| Heartbeat unreliable | Trigger the skill from Slack ("check inbox") for the live part. |
| Slack fails during demo | The dashboard alone, then the backup video. |
| Wifi-off breaks something | Practice it twice before 17:00; if flaky, show it in the backup video. |
| Venue wifi slow | Use the SSD: models, packages, Docker images. |

---

## Part 16: Bring + morning checklist

**Bring:** laptops, chargers, USB-C SSD (models, `invoice-watchdog`, wheels, Mailpit image), HDMI and USB-C adapters, phone with Slack, tokens in a password manager, snacks and water.

- [ ] Ask organizers about pre-written code and team size
- [x] Docker, Node, Python, uv, Git, Ollama on Ananya's laptop
- [x] Python packages + ARM64 wheels downloaded
- [x] Mailpit ARM64 image saved
- [x] Fake data set v3 (Bolt PO at $13.44, receipts, carton review case, layered answer key)
- [ ] Find which teammate has Nemotron Super and Qwen 32B; copy to SSD
- [ ] Copy `invoice-watchdog` to SSD
- [ ] Slack workspace + app + both tokens (Telegram token optional)
- [ ] NemoClaw practice install on one laptop
- [ ] Everyone reads Parts 1–3 and their study list

---

## Sources

- Event page: https://builderbase.com/event/dell-x-nvidia-ai-hackathon-san-francisco
- NVIDIA NemoClaw Quickstart: https://docs.nvidia.com/nemoclaw/latest/get-started/quickstart.html
- NemoClaw on GX10 (GB10) from scratch, third-party: https://ai-muninn.com/en/blog/nemoclaw-install-gx10-from-scratch
