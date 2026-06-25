# ARCHITECTURE

## 1. What does your memory system store, and why did you structure it that way?

Memory is stored in SQLite because the assignment requires persistence across sessions and structured knowledge, not just prompt logs. It has two main layers. **Execution Memory** stores instructions, decomposed plans, step outcomes, API calls, duration, failures, and structured reports. The agent uses this to recognize similar tasks and reuse successful decompositions. **Capability Memory** stores known operations, generated API templates, success/failure counts, average API calls, average duration, and discovered constraints. The agent uses this to decide whether to reuse an existing capability, synthesize a missing one, or avoid approaches that previously failed.

## 2. How does capability synthesis work in your implementation?

When the planner encounters a task that needs a capability not present in memory, the agent creates a capability gap. For the triage task, the missing operation is complex GitHub issue search. At runtime, the synthesizer reasons that the required operation can be expressed as a GitHub REST API template: `GET /search/issues` with a generated query like `repo:{owner}/{repo} is:issue is:open no:assignee`. It then tests the generated implementation with a real GitHub API call. If the test succeeds, it registers the generated template as `github.search_issues` in capability memory and immediately uses it. If it fails after configured attempts, the report includes exactly what was tried and why execution could not continue or why it fell back.

## 3. What is your learning signal, and what does the agent do differently on run N vs run 1?

The measurable learning signal is API calls and execution time for the same instruction pattern. On the first triage run, the agent must synthesize and validate `github.search_issues`, so the run includes extra API calls. After synthesis, the capability and the successful plan are persisted. On a later similar triage run, the agent starts by checking memory, finds the learned plan and generated search capability, skips synthesis, and directly executes the optimized API template. The `stats` command compares first-run and latest-run API calls and duration for the same pattern, proving the behaviour changed because of memory rather than because of a new prompt example.
