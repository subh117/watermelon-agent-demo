# DEMO

Run these on a disposable GitHub repository after `.env` setup.

## Before the demo

```bash
wg-agent setup
wg-agent seed-demo-data
wg-agent memory
```

Show that memory contains core capabilities but does not yet contain the synthesized `github.search_issues` capability.

## Instruction 1 — simple execution

```bash
wg-agent run "Create a bug report for the checkout button freezing on mobile with high priority"
```

Expected result:

- Natural language is decomposed into issue creation.
- The agent creates/validates needed labels.
- A GitHub issue is created.
- The structured report shows steps, API calls, decisions, and warnings if any labels had to be created.

## Instruction 2 — compound task with capability synthesis

```bash
wg-agent run "Find all open issues assigned to nobody, group them by priority, and create a weekly triage summary issue"
```

Expected result:

- The agent identifies a missing capability: complex issue search.
- It synthesizes `github.search_issues` at runtime.
- It validates the generated GitHub REST API template with a real API call.
- It persists the new capability in memory.
- It searches for unassigned open issues, groups them by priority, and creates a summary issue.

## Instruction 3 — repeated task proving learning

```bash
wg-agent run "Again, find unassigned open issues, group them by priority, and create this week's triage summary"
```

Expected result:

- The agent finds the learned plan and synthesized capability in memory.
- It skips synthesis and validation.
- It completes the task with fewer API calls than Instruction 2.
- `wg-agent stats` shows the measured before/after improvement.

## Final proof commands

```bash
wg-agent memory
wg-agent stats
```

What to point out in the call:

- `github.search_issues` now exists in capability memory.
- Execution memory shows how earlier instructions were decomposed.
- The triage instruction pattern has lower API calls on the later run.
- Reports in `runs/` show partial failure handling and structured outputs.
