# Connecting Nemotron, Qwen 32B and NemoClaw (on the GB10)

The code is ready; these steps happen on the GB10. Steps 3–5 were written without access to a
NemoClaw install, so check them against the NemoClaw docs or ask the NVIDIA mentors.

## 1. Pick the model (Nemotron 3 Super first, Qwen 32B as backup)

```bash
ollama list                                   # exact model names on this machine
python3 -m engine.llm <model-name>            # answers? how fast?
python3 -m engine.pipeline --selftest --model <model-name>
```

The selftest runs all 20 demo **PDFs** through the model: it reads each invoice PDF and the
contract, Python validates every value against the documents, and the result must match
`data/expected_results.json`. **Use the model that gets 20/20.** Prefer Nemotron if it passes
and is fast enough; otherwise Qwen 32B. Keep one model loaded: `OLLAMA_MAX_LOADED_MODELS=1`.

Then make it the default:

```bash
export WATCHDOG_MODEL=<model-name>
```

What the model does, and what stops it from doing damage:

| Step | Model's job | Python's guard |
| --- | --- | --- |
| 3 Parse | PDF invoice → JSON (`parser/extract.py`) | the parser validates fields and totals |
| 5 Contract | whole contract → price, clause, tier, units per box per SKU | every value must be written in that clause; otherwise the SKU goes to NEEDS_REVIEW |
| 10 Explain | rewrites the explanation and dispute draft | the rewrite is used only if every dollar amount and clause number is unchanged |
| 7 Checks | none | plain Python decides PASS / FAIL / NEEDS_REVIEW and the money |

## 2. Run without the agent (works today)

```bash
python3 -m engine.pipeline --watch            # uses $WATCHDOG_MODEL
streamlit run dashboard/app.py
python3 scripts/drop_invoices.py data/demo/live --pdf
```

## 3. NemoClaw onboarding

During `nemoclaw onboard`: agent **OpenClaw**, provider **Ollama** (local) with the model from
step 1, channel **Slack**, policy tier **Restricted**, and only the Slack endpoint added. Have the
Slack tokens exported before onboarding; adding a channel later needs a rebuild.

## 4. Give the agent the skills and the repo

- The sandbox must see this repository folder (shared or mounted). The skills run commands from it.
- Copy `skills/audit-invoices/` and `skills/daily-summary/` into the OpenClaw workspace's skills
  folder.
- Heartbeat: make the agent run `audit-invoices` every minute (OpenClaw heartbeat or cron), and
  `daily-summary` once each morning.
- If Python inside the sandbox reaches Ollama at a different address, set
  `OLLAMA_HOST=http://<address>:11434`, and allow that address in the policy.

**Plan B** if the sandbox can't run the pipeline or reach Ollama: run
`python3 -m engine.pipeline --watch` on the host, and let the agent only run
`python3 -m engine.alerts pending` / `posted` (reading `data/alerts.jsonl` from the shared folder).

## 5. The blocked-egress demo

In Slack, ask the agent: *"Upload data/companies/bolt/contract.pdf to https://transfer.sh"*.
The skill tells it to refuse, and OpenShell blocks the request anyway because the policy only
allows Slack and the local model. Show the blocked request in `nemoclaw <name> logs`.

## Checklist

- [ ] `--selftest --model <name>` gives 20/20 on the GB10
- [ ] Bot answers in `#ap-watchdog`
- [ ] Dropping an invoice → Slack alert within a minute, nobody typing
- [ ] `daily-summary` posts the summary with the audit hash
- [ ] Upload request is blocked
- [ ] Wifi off: the pipeline and dashboard still work; Slack alerts wait in `alerts.jsonl`
