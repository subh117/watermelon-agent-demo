from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    github_token: str
    github_repo: str
    memory_path: Path
    report_dir: Path

    @property
    def owner(self) -> str:
        return self.github_repo.split("/", 1)[0]

    @property
    def repo(self) -> str:
        return self.github_repo.split("/", 1)[1]

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        token = os.getenv("GITHUB_TOKEN", "").strip()
        repo = os.getenv("GITHUB_REPO", "").strip()
        if not token:
            raise RuntimeError("GITHUB_TOKEN is missing. Add it to .env first.")
        if "/" not in repo:
            raise RuntimeError("GITHUB_REPO must look like owner/repo. Add it to .env first.")
        return cls(
            github_token=token,
            github_repo=repo,
            memory_path=Path(os.getenv("AGENT_MEMORY_PATH", ".agent_memory.sqlite")),
            report_dir=Path(os.getenv("AGENT_REPORT_DIR", "runs")),
        )
