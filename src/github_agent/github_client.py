from __future__ import annotations

import json
import time
from typing import Any, Optional
import requests
from .config import Settings


class GitHubApiError(RuntimeError):
    def __init__(self, method: str, path: str, status_code: int, response: Any):
        self.method = method
        self.path = path
        self.status_code = status_code
        self.response = response
        super().__init__(f"GitHub API error {status_code} for {method} {path}: {response}")


class GitHubClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = "https://api.github.com"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {settings.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "watermelon-autonomous-github-agent",
            }
        )
        self.api_calls = 0
        self.last_rate_limit_remaining: Optional[str] = None

    @property
    def owner_repo(self) -> str:
        return self.settings.github_repo

    def reset_counter(self) -> None:
        self.api_calls = 0

    def _request(self, method: str, path: str, *, params: Optional[dict[str, Any]] = None, body: Optional[dict[str, Any]] = None) -> Any:
        self.api_calls += 1
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        response = self.session.request(method, url, params=params, json=body, timeout=30)
        self.last_rate_limit_remaining = response.headers.get("X-RateLimit-Remaining")
        if response.status_code == 204:
            return None
        try:
            payload = response.json()
        except json.JSONDecodeError:
            payload = response.text
        if response.status_code >= 400:
            raise GitHubApiError(method, path, response.status_code, payload)
        return payload

    def get_repo(self) -> dict[str, Any]:
        return self._request("GET", f"/repos/{self.owner_repo}")

    def list_labels(self) -> list[dict[str, Any]]:
        labels: list[dict[str, Any]] = []
        page = 1
        while True:
            batch = self._request("GET", f"/repos/{self.owner_repo}/labels", params={"per_page": 100, "page": page})
            labels.extend(batch)
            if len(batch) < 100:
                return labels
            page += 1

    def ensure_label(self, name: str, color: str = "ededed", description: str = "Created by Watermelon agent") -> dict[str, Any]:
        try:
            return self._request("GET", f"/repos/{self.owner_repo}/labels/{name}")
        except GitHubApiError as exc:
            if exc.status_code != 404:
                raise
        return self._request(
            "POST",
            f"/repos/{self.owner_repo}/labels",
            body={"name": name, "color": color, "description": description},
        )

    def create_issue(self, title: str, body: str, labels: Optional[list[str]] = None, assignees: Optional[list[str]] = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        if assignees:
            payload["assignees"] = assignees
        return self._request("POST", f"/repos/{self.owner_repo}/issues", body=payload)

    def list_open_issues(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        page = 1
        while True:
            batch = self._request(
                "GET",
                f"/repos/{self.owner_repo}/issues",
                params={"state": "open", "per_page": 100, "page": page},
            )
            # GitHub issues endpoint includes pull requests. Exclude PRs.
            issues.extend([item for item in batch if "pull_request" not in item])
            if len(batch) < 100:
                return issues
            page += 1

    def close_issue(self, number: int, reason: str = "completed") -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/repos/{self.owner_repo}/issues/{number}",
            body={"state": "closed", "state_reason": reason},
        )

    def execute_dynamic(self, implementation: dict[str, Any], variables: dict[str, Any]) -> Any:
        """Execute a synthesized GitHub REST API template.

        The agent stores generated capabilities as data, not Python functions. This
        generic executor fills the path/params/body template and makes a real API call.
        """
        if implementation.get("type") != "github_rest_template":
            raise ValueError(f"Unsupported dynamic capability type: {implementation.get('type')}")
        method = implementation["method"]
        path = self._format_template(implementation["path"], variables)
        params = {k: self._format_template(v, variables) for k, v in implementation.get("params", {}).items()}
        body_template = implementation.get("body")
        body = None
        if body_template is not None:
            body = {k: self._format_template(v, variables) for k, v in body_template.items()}
        return self._request(method, path, params=params or None, body=body)

    def _format_template(self, value: Any, variables: dict[str, Any]) -> Any:
        if isinstance(value, str):
            return value.format(**variables)
        if isinstance(value, list):
            return [self._format_template(v, variables) for v in value]
        if isinstance(value, dict):
            return {k: self._format_template(v, variables) for k, v in value.items()}
        return value

    def create_demo_data(self) -> dict[str, Any]:
        """Seed a disposable repo with stable demo data.

        The method is idempotent enough for a demo: it checks existing issue titles
        and only creates missing demo issues.
        """
        labels = {
            "bug": ("d73a4a", "Bug report"),
            "enhancement": ("a2eeef", "Feature or improvement"),
            "priority-high": ("b60205", "High priority"),
            "priority-medium": ("fbca04", "Medium priority"),
            "priority-low": ("0e8a16", "Low priority"),
            "triage-summary": ("5319e7", "Created by the triage agent"),
        }
        created_labels = []
        for name, (color, description) in labels.items():
            self.ensure_label(name, color=color, description=description)
            created_labels.append(name)

        existing_titles = {issue["title"] for issue in self.list_open_issues()}
        demo_issues = [
            ("[watermelon-demo] Login timeout after idle session", ["bug", "priority-high"]),
            ("[watermelon-demo] Add empty state for project board", ["enhancement", "priority-medium"]),
            ("[watermelon-demo] Improve copy on invite modal", ["enhancement", "priority-low"]),
            ("[watermelon-demo] Checkout freezes on mobile Safari", ["bug", "priority-high"]),
        ]
        created_issues = []
        for title, issue_labels in demo_issues:
            if title in existing_titles:
                continue
            issue = self.create_issue(
                title=title,
                body="Seed issue for the Watermelon autonomous agent demo. Leave unassigned for triage.",
                labels=issue_labels,
            )
            created_issues.append({"number": issue["number"], "title": issue["title"]})
            time.sleep(0.2)
        return {"labels": created_labels, "created_issues": created_issues}
