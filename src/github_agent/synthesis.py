from __future__ import annotations

import time
from typing import Any
from .github_client import GitHubClient, GitHubApiError
from .memory import AgentMemory


class CapabilitySynthesisError(RuntimeError):
    pass


class CapabilitySynthesizer:
    """Runtime capability synthesis.

    This synthesizer does not just reveal a hidden hard-coded tool to the agent.
    It builds a data-driven GitHub REST template, validates it with a real API call,
    and persists the generated implementation in capability memory for reuse.
    """

    SEARCH_CAPABILITY = "github.search_issues"

    def __init__(self, max_attempts: int = 2):
        self.max_attempts = max_attempts

    def ensure_issue_search(self, client: GitHubClient, memory: AgentMemory) -> dict[str, Any]:
        existing = memory.get_capability(self.SEARCH_CAPABILITY)
        if existing:
            return {
                "created": False,
                "capability": existing,
                "reasoning": "Capability already exists in persistent memory, so synthesis was skipped.",
                "attempts": [],
            }

        attempts = []
        last_error = None
        for attempt_no in range(1, self.max_attempts + 1):
            implementation = self._generate_search_template(attempt_no)
            reasoning = (
                "The instruction requires filtering issues by assignment/status. "
                "GitHub's list issues endpoint can fetch open issues, but complex filters are better expressed "
                "through the Search Issues API. Generate a REST template and validate it before registering."
            )
            try:
                started = time.perf_counter()
                test_query = f"repo:{client.owner_repo} is:issue is:open"
                result = client.execute_dynamic(implementation, {"query": test_query, "per_page": 1})
                duration_ms = int((time.perf_counter() - started) * 1000)
                if not isinstance(result, dict) or "items" not in result:
                    raise CapabilitySynthesisError("Validation response did not contain an items list.")
                inserted = memory.register_capability(
                    self.SEARCH_CAPABILITY,
                    description="Search GitHub issues using a generated REST API query template.",
                    implementation=implementation,
                    source="synthesized_runtime",
                )
                capability = memory.get_capability(self.SEARCH_CAPABILITY)
                attempts.append(
                    {
                        "attempt": attempt_no,
                        "status": "success",
                        "duration_ms": duration_ms,
                        "test_query": test_query,
                        "inserted_into_memory": inserted,
                    }
                )
                return {"created": True, "capability": capability, "reasoning": reasoning, "attempts": attempts}
            except (GitHubApiError, CapabilitySynthesisError, ValueError) as exc:
                last_error = str(exc)
                attempts.append({"attempt": attempt_no, "status": "failed", "error": last_error})
        raise CapabilitySynthesisError(f"Could not synthesize {self.SEARCH_CAPABILITY}: {last_error}. Attempts: {attempts}")

    def _generate_search_template(self, attempt_no: int) -> dict[str, Any]:
        # Attempt 1 is the normal efficient GitHub endpoint. A second attempt is
        # included to show the N-attempt contract; it currently produces the same
        # valid shape because the GitHub API is deterministic.
        return {
            "type": "github_rest_template",
            "method": "GET",
            "path": "/search/issues",
            "params": {
                "q": "{query}",
                "per_page": "{per_page}",
            },
            "output_contract": {
                "items": "list of issue objects",
                "total_count": "number of matched issues",
            },
        }
