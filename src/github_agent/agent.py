from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .github_client import GitHubClient, GitHubApiError
from .memory import AgentMemory
from .models import ExecutionReport, Plan, PlanStep, Status, StepReport, utc_now_iso
from .planner import Planner
from .synthesis import CapabilitySynthesizer, CapabilitySynthesisError


LABEL_COLORS = {
    "bug": "d73a4a",
    "enhancement": "a2eeef",
    "priority-high": "b60205",
    "priority-medium": "fbca04",
    "priority-low": "0e8a16",
    "triage-summary": "5319e7",
}


class GitHubIntelligenceAgent:
    def __init__(self, memory: AgentMemory, client: GitHubClient, report_dir: Path):
        self.memory = memory
        self.client = client
        self.report_dir = Path(report_dir)
        self.planner = Planner()
        self.synthesizer = CapabilitySynthesizer()
        self._last_issue_set: list[dict[str, Any]] = []
        self._last_grouped_issues: dict[str, list[dict[str, Any]]] = {}

    def register_core_capabilities(self) -> list[str]:
        """Register built-in capabilities. Synthesized capabilities are not inserted here."""
        core = [
            (
                "github.create_issue",
                "Create a GitHub issue with title, body, labels, and optional assignees.",
                {"type": "python_bound", "method": "GitHubClient.create_issue"},
            ),
            (
                "github.list_open_issues",
                "List open GitHub issues. Used as a fallback when search capability is unavailable.",
                {"type": "python_bound", "method": "GitHubClient.list_open_issues"},
            ),
            (
                "github.ensure_label",
                "Create a label if missing before applying it to issues.",
                {"type": "python_bound", "method": "GitHubClient.ensure_label"},
            ),
            (
                "local.group_by_priority",
                "Group issue objects by priority labels discovered on the issue.",
                {"type": "local_transform", "method": "group_by_priority"},
            ),
        ]
        inserted = []
        for name, desc, impl in core:
            if self.memory.register_capability(name, desc, impl, source="core_static"):
                inserted.append(name)
        return inserted

    def run(self, instruction: str) -> ExecutionReport:
        self.register_core_capabilities()
        self.client.reset_counter()
        before_snapshot = self.memory.snapshot()
        started_at = utc_now_iso()
        run_start = time.perf_counter()
        decisions: list[str] = []
        failures: list[str] = []
        step_reports: list[StepReport] = []

        fresh_plan = self.planner.plan(instruction)
        learned = self.memory.get_learned_plan(fresh_plan.pattern_key)
        if learned and fresh_plan.pattern_key != "unknown":
            learned_plan = self.planner.with_learned_plan(instruction, learned)
            if learned_plan:
                plan = learned_plan
                decisions.append(
                    f"Reused learned plan for pattern '{plan.pattern_key}' from execution memory "
                    f"(previous avg API calls: {learned['avg_api_calls']:.2f})."
                )
            else:
                plan = fresh_plan
                decisions.append("Found learned plan memory, but could not safely rehydrate it. Used fresh plan.")
        else:
            plan = fresh_plan
            decisions.append(f"Created a fresh plan with confidence {plan.confidence:.2f}.")

        run_id = self.memory.start_execution(instruction, plan.pattern_key, plan.model_dump())
        status = Status.success

        if plan.intent == "unsupported":
            status = Status.failed
            failures.append(plan.steps[0].inputs.get("reason", "Unsupported instruction"))
        else:
            for idx, step in enumerate(plan.steps, start=1):
                api_before = self.client.api_calls
                step_start = time.perf_counter()
                try:
                    output_summary, output_payload, warnings = self._execute_step(step, decisions)
                    duration_ms = int((time.perf_counter() - step_start) * 1000)
                    api_calls = self.client.api_calls - api_before
                    step_report = StepReport(
                        index=idx,
                        name=step.name,
                        capability=step.capability,
                        status=Status.success,
                        api_calls=api_calls,
                        duration_ms=duration_ms,
                        inputs=step.inputs,
                        output_summary=output_summary,
                        warnings=warnings,
                    )
                    self.memory.record_step(
                        run_id,
                        step.name,
                        step.capability,
                        "success",
                        api_calls,
                        duration_ms,
                        None,
                        output_payload,
                    )
                    self.memory.update_capability_metrics(step.capability, True, duration_ms, api_calls)
                    step_reports.append(step_report)
                except Exception as exc:  # noqa: BLE001 - report all failures with context
                    duration_ms = int((time.perf_counter() - step_start) * 1000)
                    api_calls = self.client.api_calls - api_before
                    error = str(exc)
                    failures.append(f"Step '{step.name}' failed: {error}")
                    self.memory.record_step(
                        run_id,
                        step.name,
                        step.capability,
                        "failed",
                        api_calls,
                        duration_ms,
                        error,
                        {},
                    )
                    self.memory.update_capability_metrics(step.capability, False, duration_ms, api_calls)
                    step_reports.append(
                        StepReport(
                            index=idx,
                            name=step.name,
                            capability=step.capability,
                            status=Status.failed,
                            api_calls=api_calls,
                            duration_ms=duration_ms,
                            inputs=step.inputs,
                            error=error,
                        )
                    )
                    if step.critical:
                        status = Status.partial if idx > 1 else Status.failed
                        decisions.append(
                            f"Stopped after critical failure in step {idx}; no silent half-complete success was reported."
                        )
                        break
            else:
                status = Status.success

        duration_ms = int((time.perf_counter() - run_start) * 1000)
        after_snapshot = self.memory.snapshot()
        memory_changes = self.memory.diff_snapshot(before_snapshot, after_snapshot)

        metrics = {
            "api_calls_total": self.client.api_calls,
            "duration_ms_total": duration_ms,
            "rate_limit_remaining": self.client.last_rate_limit_remaining,
            "pattern_key": plan.pattern_key,
        }

        report = ExecutionReport(
            run_id=run_id,
            instruction=instruction,
            status=status,
            started_at=started_at,
            duration_ms=duration_ms,
            api_call_count=self.client.api_calls,
            plan=plan.model_dump(),
            steps=step_reports,
            decisions=decisions,
            failures=failures,
            memory_changes=memory_changes,
            metrics=metrics,
        )
        self.memory.finish_execution(run_id, status.value, self.client.api_calls, duration_ms, report.model_dump())
        self.memory.save_learned_plan(plan.pattern_key, plan.model_dump(), self.client.api_calls, duration_ms, status == Status.success)
        self._write_report(report)
        return report

    def _execute_step(self, step: PlanStep, decisions: list[str]) -> tuple[str, dict[str, Any], list[str]]:
        if step.name == "create_github_issue":
            return self._step_create_issue(step)
        if step.name == "find_unassigned_open_issues":
            return self._step_find_unassigned(step, decisions)
        if step.name == "group_issues_by_priority":
            return self._step_group_by_priority(step)
        if step.name == "create_weekly_triage_summary_issue":
            return self._step_create_triage_summary(step)
        raise ValueError(f"No executor for step '{step.name}'")

    def _step_create_issue(self, step: PlanStep) -> tuple[str, dict[str, Any], list[str]]:
        labels = list(step.inputs.get("labels", []))
        warnings = self._ensure_labels(labels)
        try:
            issue = self.client.create_issue(
                title=step.inputs["title"],
                body=step.inputs.get("body", "Created by autonomous agent."),
                labels=labels,
            )
        except GitHubApiError as exc:
            if exc.status_code == 422 and labels:
                # Learn a platform constraint and retry without labels instead of silently failing.
                self.memory.record_constraint(
                    "github.issue_labels_must_exist_or_be_valid",
                    {"error": str(exc), "attempted_labels": labels},
                    confidence=0.9,
                )
                warnings.append("GitHub rejected one or more labels. Retried issue creation without labels.")
                issue = self.client.create_issue(
                    title=step.inputs["title"],
                    body=step.inputs.get("body", "Created by autonomous agent."),
                    labels=[],
                )
            else:
                raise
        return (
            f"Created issue #{issue['number']}: {issue['title']}",
            {"number": issue["number"], "url": issue["html_url"], "title": issue["title"]},
            warnings,
        )

    def _step_find_unassigned(self, step: PlanStep, decisions: list[str]) -> tuple[str, dict[str, Any], list[str]]:
        warnings: list[str] = []
        cap = self.memory.get_capability("github.search_issues")
        if not cap:
            decisions.append("Capability gap detected: github.search_issues is missing. Starting runtime synthesis.")
            try:
                synthesis = self.synthesizer.ensure_issue_search(self.client, self.memory)
                cap = synthesis["capability"]
                decisions.append(
                    "Synthesized github.search_issues and validated it with a real GitHub API call. "
                    f"Attempts: {synthesis['attempts']}"
                )
            except CapabilitySynthesisError as exc:
                warnings.append(f"Synthesis failed, falling back to list_open_issues: {exc}")
                self.memory.record_constraint("github.search_issues_synthesis_failed", {"error": str(exc)}, confidence=0.8)
                issues = self.client.list_open_issues()
                unassigned = [i for i in issues if not i.get("assignees")]
                self._last_issue_set = self._simplify_issues(unassigned)
                return (
                    f"Found {len(self._last_issue_set)} unassigned open issues using fallback list/filter.",
                    {"issues": self._last_issue_set, "method": "fallback_list_filter"},
                    warnings,
                )
        query = f"repo:{self.client.owner_repo} is:issue is:open no:assignee"
        result = self.client.execute_dynamic(cap["implementation"], {"query": query, "per_page": 100})
        items = result.get("items", []) if isinstance(result, dict) else []
        self._last_issue_set = self._simplify_issues(items)
        return (
            f"Found {len(self._last_issue_set)} unassigned open issues using synthesized search capability.",
            {"issues": self._last_issue_set, "method": "synthesized_search", "query": query},
            warnings,
        )

    def _step_group_by_priority(self, step: PlanStep) -> tuple[str, dict[str, Any], list[str]]:
        grouped: dict[str, list[dict[str, Any]]] = {"high": [], "medium": [], "low": [], "none": []}
        for issue in self._last_issue_set:
            priority = self._priority_for_issue(issue)
            grouped[priority].append(issue)
        self._last_grouped_issues = grouped
        counts = {k: len(v) for k, v in grouped.items()}
        return f"Grouped issues by priority: {counts}", {"counts": counts, "groups": grouped}, []

    def _step_create_triage_summary(self, step: PlanStep) -> tuple[str, dict[str, Any], list[str]]:
        warnings = self._ensure_labels(["triage-summary"])
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        title = f"Weekly triage summary - {now}"
        body = self._render_triage_body()
        issue = self.client.create_issue(title=title, body=body, labels=["triage-summary"])
        return (
            f"Created triage summary issue #{issue['number']} with {sum(len(v) for v in self._last_grouped_issues.values())} items.",
            {"number": issue["number"], "url": issue["html_url"], "title": issue["title"]},
            warnings,
        )

    def _ensure_labels(self, labels: list[str]) -> list[str]:
        warnings: list[str] = []
        for label in labels:
            color = LABEL_COLORS.get(label, "ededed")
            try:
                self.client.ensure_label(label, color=color, description="Created/validated by Watermelon agent")
            except GitHubApiError as exc:
                self.memory.record_constraint(
                    "github.label_create_or_read_failed",
                    {"label": label, "error": str(exc)},
                    confidence=0.8,
                )
                warnings.append(f"Could not ensure label '{label}': {exc}")
                raise
        return warnings

    def _simplify_issues(self, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        simplified = []
        for issue in issues:
            simplified.append(
                {
                    "number": issue.get("number"),
                    "title": issue.get("title"),
                    "url": issue.get("html_url"),
                    "labels": [label.get("name") for label in issue.get("labels", [])],
                    "assignees": [user.get("login") for user in issue.get("assignees", [])],
                }
            )
        return simplified

    def _priority_for_issue(self, issue: dict[str, Any]) -> str:
        labels = {str(label).lower() for label in issue.get("labels", [])}
        if "priority-high" in labels or "p1" in labels or "high" in labels:
            return "high"
        if "priority-medium" in labels or "p2" in labels or "medium" in labels:
            return "medium"
        if "priority-low" in labels or "p3" in labels or "low" in labels:
            return "low"
        return "none"

    def _render_triage_body(self) -> str:
        lines = [
            "Created by the Autonomous GitHub Intelligence Agent.",
            "",
            "The agent found open issues assigned to nobody and grouped them by priority.",
            "",
        ]
        for priority in ["high", "medium", "low", "none"]:
            issues = self._last_grouped_issues.get(priority, [])
            lines.append(f"## Priority: {priority} ({len(issues)})")
            if not issues:
                lines.append("No issues found.")
            else:
                for issue in issues:
                    lines.append(f"- #{issue['number']} — {issue['title']} ({issue['url']})")
            lines.append("")
        lines.extend(
            [
                "---",
                "Memory note: if this task is run again, the agent will reuse the synthesized GitHub issue search capability instead of synthesizing it again.",
            ]
        )
        return "\n".join(lines)

    def _write_report(self, report: ExecutionReport) -> None:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        path = self.report_dir / f"run_{report.run_id}.json"
        path.write_text(json.dumps(report.model_dump(), indent=2), encoding="utf-8")
