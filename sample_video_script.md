# 15-minute walkthrough script

Use this as your speaking flow while recording the demo video.

## 0:00–1:00 — Problem framing

I chose GitHub because humans often do multi-step work there: creating issues, triaging backlogs, summarizing work, and managing labels. The goal is not a thin API wrapper. The goal is an agent that can take a natural language instruction, decide what to do, execute it, remember what happened, and improve on repeated work.

## 1:00–3:00 — Architecture

Show `ARCHITECTURE.md`.

Explain the two memory layers:

- Execution memory: instructions, decompositions, step outcomes, API calls, timing, reports.
- Capability memory: operations the agent knows, synthesized implementations, success rates, constraints.

Then explain that capability synthesis creates a GitHub REST API template at runtime and validates it with a real API call before saving it.

## 3:00–5:00 — Setup and initial memory

Run:

```bash
wg-agent setup
wg-agent seed-demo-data
wg-agent memory
```

Point out that `github.search_issues` is not in memory yet.

## 5:00–7:00 — Simple instruction

Run:

```bash
wg-agent run "Create a bug report for the checkout button freezing on mobile with high priority"
```

Open the GitHub repo and show the created issue. Then show the JSON report: plan, steps, API calls, and decisions.

## 7:00–11:00 — Compound instruction with synthesis

Run:

```bash
wg-agent run "Find all open issues assigned to nobody, group them by priority, and create a weekly triage summary issue"
```

Point out the decisions section:

- capability gap detected
- runtime synthesis started
- generated `/search/issues` template
- validation API call succeeded
- capability registered into memory

Open GitHub and show the summary issue.

## 11:00–13:00 — Run again to prove learning

Run:

```bash
wg-agent run "Again, find unassigned open issues, group them by priority, and create this week's triage summary"
```

Point out that synthesis was skipped. The agent reused the learned capability and the learned plan.

## 13:00–15:00 — Metrics

Run:

```bash
wg-agent memory
wg-agent stats
```

Explain the before/after numbers. For example, the first triage run used extra API calls because it had to synthesize and test the capability. The repeated run used fewer calls because the generated capability and plan persisted in SQLite.

End with what you would improve next: add rollback, add more GitHub workflows like release notes, and add a real LLM parser for broader natural language coverage.
