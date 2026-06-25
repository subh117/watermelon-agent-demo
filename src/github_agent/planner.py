from __future__ import annotations

import re
from typing import Optional
from .models import Plan, PlanStep


class Planner:
    """Small deterministic planner for the demo instruction space.

    This is intentionally transparent so the walkthrough can focus on the memory,
    synthesis, and learning loop instead of hiding everything behind an LLM call.
    """

    def plan(self, instruction: str) -> Plan:
        text = instruction.strip()
        lowered = text.lower()
        if self._looks_like_triage(lowered):
            return Plan(
                pattern_key="triage_unassigned_by_priority",
                intent="triage_summary",
                confidence=0.91,
                steps=[
                    PlanStep(
                        name="find_unassigned_open_issues",
                        capability="github.search_issues",
                        inputs={"query_kind": "unassigned_open_issues"},
                    ),
                    PlanStep(
                        name="group_issues_by_priority",
                        capability="local.group_by_priority",
                        inputs={},
                    ),
                    PlanStep(
                        name="create_weekly_triage_summary_issue",
                        capability="github.create_issue",
                        inputs={"label": "triage-summary"},
                    ),
                ],
            )
        if "bug" in lowered or "issue" in lowered or "report" in lowered:
            priority = self._extract_priority(lowered)
            title = self._extract_issue_title(text)
            labels = ["bug"] if "bug" in lowered or "report" in lowered else []
            if priority:
                labels.append(f"priority-{priority}")
            return Plan(
                pattern_key="create_bug_report" if "bug" in lowered or "report" in lowered else "create_issue",
                intent="create_issue",
                confidence=0.86,
                steps=[
                    PlanStep(
                        name="create_github_issue",
                        capability="github.create_issue",
                        inputs={
                            "title": title,
                            "body": self._issue_body(text, priority),
                            "labels": labels,
                        },
                    )
                ],
            )
        return Plan(
            pattern_key="unknown",
            intent="unsupported",
            confidence=0.2,
            steps=[
                PlanStep(
                    name="unsupported_instruction",
                    capability="none",
                    inputs={"reason": "The planner could not map this instruction to a supported GitHub workflow."},
                    critical=True,
                )
            ],
        )

    def with_learned_plan(self, instruction: str, learned: dict) -> Optional[Plan]:
        """Rehydrate a successful previous decomposition from execution memory."""
        plan_data = learned.get("plan")
        if not plan_data:
            return None
        try:
            plan = Plan.model_validate(plan_data)
            plan.source = "learned_plan_memory"
            return plan
        except Exception:
            return None

    def _looks_like_triage(self, lowered: str) -> bool:
        return (
            ("unassigned" in lowered or "assigned to nobody" in lowered or "nobody" in lowered)
            and "open" in lowered
            and ("priority" in lowered or "group" in lowered)
            and ("summary" in lowered or "triage" in lowered)
        )

    def _extract_priority(self, lowered: str) -> Optional[str]:
        for p in ["high", "medium", "low"]:
            if p in lowered:
                return p
        if "p1" in lowered or "urgent" in lowered:
            return "high"
        if "p2" in lowered:
            return "medium"
        if "p3" in lowered:
            return "low"
        return None

    def _extract_issue_title(self, instruction: str) -> str:
        # Examples: "Create a bug report for checkout freezing" -> "Checkout freezing"
        match = re.search(r"(?:for|about)\s+(.+)$", instruction, flags=re.IGNORECASE)
        if match:
            title = match.group(1).strip().rstrip(".")
        else:
            title = instruction.strip().rstrip(".")
        # Remove trailing priority wording.
        title = re.sub(r"\s+with\s+(high|medium|low)\s+priority$", "", title, flags=re.IGNORECASE)
        return title[:1].upper() + title[1:]

    def _issue_body(self, instruction: str, priority: Optional[str]) -> str:
        lines = [
            "Created by the Autonomous GitHub Intelligence Agent.",
            "",
            "## Original instruction",
            instruction,
            "",
            "## Agent interpretation",
            "This should be tracked as a GitHub issue created from a natural language request.",
        ]
        if priority:
            lines.extend(["", "## Priority", priority])
        return "\n".join(lines)
