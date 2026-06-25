# Watermelon Assignment — Autonomous GitHub Intelligence Agent

This repository implements an **Autonomous Platform Intelligence Agent** for **GitHub**.

The agent accepts a natural language instruction, decomposes it into executable steps, makes real GitHub API calls, persists structured memory across runs, synthesizes a new capability at runtime, and shows measurable self-learning through reduced API calls on repeated tasks.

## Why GitHub?

GitHub has meaningful multi-step human workflows: issue creation, backlog triage, label-based prioritization, release planning, and status reporting. This assignment is implemented against GitHub Issues so the demo is easy to run safely inside a disposable repository.

## What this demonstrates

| Requirement | Where it is implemented |
|---|---|
| Natural language instruction → platform execution | `planner.py`, `agent.py`, `github_client.py` |
| Persistent execution + capability memory | `memory.py` with SQLite tables |
| Memory actively changes behaviour | learned plans + synthesized capability reuse |
| Runtime capability synthesis | `synthesis.py` creates and validates `github.search_issues` dynamically |
| Self-learning with real metrics | `execution_runs`, `capabilities`, `learned_plans` track API calls and duration |
| Structured execution report | JSON report after every run in `runs/` |
| Partial failure handling | step-level status, warnings, failure reasons, and no silent success |

## Quick start

### 1. Create a test GitHub repo

Create a disposable repository, for example:

```text
your-github-username/watermelon-agent-demo
```

Do not use a production repository for the demo.

### 2. Create a GitHub token

Use either:

- Classic token with `repo` scope for private repositories, or
- Fine-grained token with repository access and **Issues read/write** permission.

### 3. Install and configure

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env
```

Edit `.env`:

```bash
GITHUB_TOKEN=your_token_here
GITHUB_REPO=your-username/watermelon-agent-demo
```

### 4. Validate setup

```bash
wg-agent setup
```

This initializes SQLite memory, registers core capabilities, and verifies the GitHub repo is reachable.

### 5. Seed demo data

```bash
wg-agent seed-demo-data
```

This creates a few demo issues and labels so the triage instruction has real data to process.

## Live demo commands

### Show memory before the agent learns

```bash
wg-agent memory
```

### Instruction 1 — simple platform execution

```bash
wg-agent run "Create a bug report for the checkout button freezing on mobile with high priority"
```

Expected: creates a GitHub issue, applies `bug` and `priority-high` labels, and returns a structured execution report.

### Instruction 2 — compound task + runtime synthesis

```bash
wg-agent run "Find all open issues assigned to nobody, group them by priority, and create a weekly triage summary issue"
```

Expected:

1. The agent detects that it needs complex issue search.
2. It does not have `github.search_issues` in capability memory.
3. It synthesizes the capability at runtime as a GitHub REST API template.
4. It validates the generated capability using a real GitHub API call.
5. It registers the capability into persistent memory.
6. It uses the capability to retrieve unassigned open issues.
7. It groups the issues by priority label.
8. It creates a triage summary issue.

### Instruction 3 — repeated task showing self-learning

```bash
wg-agent run "Again, find unassigned open issues, group them by priority, and create this week's triage summary"
```

Expected: the agent reuses the synthesized `github.search_issues` capability and learned plan from memory. It should skip the synthesis test call, use fewer API calls than the previous triage run, and report the before/after metric.

### Show learning metrics

```bash
wg-agent stats
```

You should see something like:

```text
Pattern: triage_unassigned_by_priority
Runs: 2
First run API calls: 4
Latest run API calls: 2
Improvement: 50.0%
```

The exact number may vary by repo state, but the second similar run should use fewer calls because capability synthesis is no longer needed.

## Useful commands

```bash
wg-agent memory          # inspect execution + capability memory
wg-agent stats           # measurable learning signal
wg-agent run "..."       # run a natural language instruction
wg-agent seed-demo-data  # create demo issues and labels
wg-agent reset-memory    # only for local testing; do not use before the live demo
```

## How partial failures are handled

Every run creates a structured report with:

- Completed steps
- Failed steps
- API calls per step
- Agent decisions
- Memory changes
- Platform constraints learned

If a step fails, the agent reports the partial state. It does not silently claim success.

