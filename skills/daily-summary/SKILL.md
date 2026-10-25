---
name: daily-summary
description: Post the morning summary of overnight invoice audits (invoices audited, failures, amount at risk, invoices needing review, latest audit-log hash) to Slack. Use once each morning, or when someone asks for the summary.
---

# Daily summary

1. From the repository folder, run:

   ```bash
   python3 -m engine.alerts summary
   ```

2. Post the printed line to `#ap-watchdog` exactly as written.

Direct route, no agent needed: `python3 -m engine.slack summary`.
Setup: `docs/SLACK_SETUP.md`.

The line ends with the latest audit-log hash. Posting it each day makes the log tamper-evident
beyond this machine: a rewritten log would no longer match the hashes already in Slack. Do not
add invoice details, prices or clause text.
