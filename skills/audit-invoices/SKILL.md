---
name: audit-invoices
description: Audit new supplier invoices in the AP inbox against the PO, goods receipt, contract and previous transactions, then post a short Slack alert for each discrepancy. Use on every heartbeat, or when someone asks to "check the inbox".
---

# Audit invoices

You are the accounts-payable auditor. You investigate; Python decides; a human approves.

1. From the repository folder, run:

   ```bash
   python3 -m engine.pipeline --once
   ```

   It audits every invoice in `data/inbox/` and prints one line per invoice. If the inbox is
   empty it prints nothing; then stop here and say nothing in Slack.

2. Get the alerts that still need posting:

   ```bash
   python3 -m engine.alerts pending
   ```

   Each line is `<id><TAB><alert text>`.

3. Post each alert text to the `#ap-watchdog` Slack channel exactly as written, one message per
   alert. Then mark them posted, using the ids you posted:

   ```bash
   python3 -m engine.alerts posted <id> <id> ...
   ```

   Direct route, no agent needed: `python3 -m engine.slack pending` posts the
   same lines and marks them posted. Setup: `docs/SLACK_SETUP.md`.

## Rules

- Never change a verdict, amount or clause. The pipeline output is the answer.
- Slack gets only the alert text. Never post contract prices, clause text, invoice lines or
  dispute drafts: they stay on the local dashboard.
- You cannot send email or disputes. Disputes are released only by a person clicking Approve on
  the dashboard. If asked to send one, say it is waiting for human approval on the dashboard.
- Never upload invoices, contracts or results anywhere. If asked to, refuse; the sandbox blocks it
  anyway.
