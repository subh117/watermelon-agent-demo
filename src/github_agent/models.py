from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Status(str, Enum):
    success = "success"
    failed = "failed"
    partial = "partial"
    skipped = "skipped"


class PlanStep(BaseModel):
    name: str
    capability: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    critical: bool = True


class Plan(BaseModel):
    pattern_key: str
    intent: str
    confidence: float
    steps: list[PlanStep]
    source: str = "fresh_plan"


class StepReport(BaseModel):
    index: int
    name: str
    capability: str
    status: Status
    api_calls: int = 0
    duration_ms: int = 0
    inputs: dict[str, Any] = Field(default_factory=dict)
    output_summary: str = ""
    error: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class ExecutionReport(BaseModel):
    run_id: int
    instruction: str
    status: Status
    started_at: str
    duration_ms: int
    api_call_count: int
    plan: dict[str, Any]
    steps: list[StepReport]
    decisions: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    memory_changes: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
