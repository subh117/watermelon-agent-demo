from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional
from .models import utc_now_iso


class AgentMemory:
    """Structured persistent memory.

    This is intentionally not a text log. The agent queries these tables to change
    future behaviour: reuse successful plans, reuse synthesized capabilities, and
    avoid platform constraints that were learned from failures.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS capabilities (
                name TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                implementation_json TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                avg_duration_ms REAL NOT NULL DEFAULT 0,
                avg_api_calls REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_used_at TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS execution_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instruction TEXT NOT NULL,
                pattern_key TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                api_call_count INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                report_json TEXT,
                created_at TEXT NOT NULL,
                finished_at TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS step_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                step_name TEXT NOT NULL,
                capability_name TEXT NOT NULL,
                status TEXT NOT NULL,
                api_calls INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                output_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES execution_runs(id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS constraints_learned (
                key TEXT PRIMARY KEY,
                details_json TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.5,
                count INTEGER NOT NULL DEFAULT 1,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS learned_plans (
                pattern_key TEXT PRIMARY KEY,
                plan_json TEXT NOT NULL,
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                avg_api_calls REAL NOT NULL DEFAULT 0,
                avg_duration_ms REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_used_at TEXT
            )
            """
        )
        self.conn.commit()

    # ---------- Capability memory ----------

    def register_capability(
        self,
        name: str,
        description: str,
        implementation: dict[str, Any],
        source: str,
        status: str = "active",
    ) -> bool:
        """Returns True if a new capability was inserted, False if it already existed."""
        now = utc_now_iso()
        cur = self.conn.cursor()
        cur.execute("SELECT name FROM capabilities WHERE name = ?", (name,))
        exists = cur.fetchone() is not None
        if exists:
            return False
        cur.execute(
            """
            INSERT INTO capabilities
            (name, description, implementation_json, source, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, description, json.dumps(implementation), source, status, now),
        )
        self.conn.commit()
        return True

    def get_capability(self, name: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM capabilities WHERE name = ? AND status = 'active'", (name,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["implementation"] = json.loads(data.pop("implementation_json"))
        return data

    def list_capabilities(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM capabilities ORDER BY created_at ASC").fetchall()
        out = []
        for row in rows:
            data = dict(row)
            data["implementation"] = json.loads(data.pop("implementation_json"))
            out.append(data)
        return out

    def update_capability_metrics(self, name: str, success: bool, duration_ms: int, api_calls: int) -> None:
        cap = self.conn.execute("SELECT * FROM capabilities WHERE name = ?", (name,)).fetchone()
        if not cap:
            return
        success_count = int(cap["success_count"])
        failure_count = int(cap["failure_count"])
        old_n = success_count + failure_count
        old_duration = float(cap["avg_duration_ms"])
        old_calls = float(cap["avg_api_calls"])
        new_n = old_n + 1
        new_duration = ((old_duration * old_n) + duration_ms) / new_n
        new_calls = ((old_calls * old_n) + api_calls) / new_n
        if success:
            success_count += 1
        else:
            failure_count += 1
        self.conn.execute(
            """
            UPDATE capabilities
            SET success_count = ?, failure_count = ?, avg_duration_ms = ?, avg_api_calls = ?, last_used_at = ?
            WHERE name = ?
            """,
            (success_count, failure_count, new_duration, new_calls, utc_now_iso(), name),
        )
        self.conn.commit()

    # ---------- Execution memory ----------

    def start_execution(self, instruction: str, pattern_key: str, plan: dict[str, Any]) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO execution_runs (instruction, pattern_key, plan_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (instruction, pattern_key, json.dumps(plan), utc_now_iso()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_execution(self, run_id: int, status: str, api_call_count: int, duration_ms: int, report: dict[str, Any]) -> None:
        self.conn.execute(
            """
            UPDATE execution_runs
            SET status = ?, api_call_count = ?, duration_ms = ?, report_json = ?, finished_at = ?
            WHERE id = ?
            """,
            (status, api_call_count, duration_ms, json.dumps(report), utc_now_iso(), run_id),
        )
        self.conn.commit()

    def record_step(
        self,
        run_id: int,
        step_name: str,
        capability_name: str,
        status: str,
        api_calls: int,
        duration_ms: int,
        error: Optional[str],
        output: dict[str, Any],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO step_results
            (run_id, step_name, capability_name, status, api_calls, duration_ms, error, output_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, step_name, capability_name, status, api_calls, duration_ms, error, json.dumps(output), utc_now_iso()),
        )
        self.conn.commit()

    def recent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, instruction, pattern_key, status, api_call_count, duration_ms, created_at FROM execution_runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- Constraint memory ----------

    def record_constraint(self, key: str, details: dict[str, Any], confidence: float = 0.7) -> None:
        now = utc_now_iso()
        existing = self.conn.execute("SELECT * FROM constraints_learned WHERE key = ?", (key,)).fetchone()
        if existing:
            self.conn.execute(
                """
                UPDATE constraints_learned
                SET details_json = ?, confidence = ?, count = count + 1, last_seen_at = ?
                WHERE key = ?
                """,
                (json.dumps(details), confidence, now, key),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO constraints_learned (key, details_json, confidence, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (key, json.dumps(details), confidence, now, now),
            )
        self.conn.commit()

    def list_constraints(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM constraints_learned ORDER BY last_seen_at DESC").fetchall()
        out = []
        for row in rows:
            data = dict(row)
            data["details"] = json.loads(data.pop("details_json"))
            out.append(data)
        return out

    # ---------- Learned plan memory ----------

    def get_learned_plan(self, pattern_key: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM learned_plans WHERE pattern_key = ?", (pattern_key,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["plan"] = json.loads(data.pop("plan_json"))
        return data

    def save_learned_plan(self, pattern_key: str, plan: dict[str, Any], api_calls: int, duration_ms: int, success: bool) -> None:
        now = utc_now_iso()
        row = self.conn.execute("SELECT * FROM learned_plans WHERE pattern_key = ?", (pattern_key,)).fetchone()
        if not row:
            self.conn.execute(
                """
                INSERT INTO learned_plans
                (pattern_key, plan_json, success_count, failure_count, avg_api_calls, avg_duration_ms, created_at, last_used_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (pattern_key, json.dumps(plan), 1 if success else 0, 0 if success else 1, api_calls, duration_ms, now, now),
            )
        else:
            success_count = int(row["success_count"]) + (1 if success else 0)
            failure_count = int(row["failure_count"]) + (0 if success else 1)
            old_n = int(row["success_count"]) + int(row["failure_count"])
            new_n = old_n + 1
            avg_api_calls = ((float(row["avg_api_calls"]) * old_n) + api_calls) / new_n
            avg_duration_ms = ((float(row["avg_duration_ms"]) * old_n) + duration_ms) / new_n
            self.conn.execute(
                """
                UPDATE learned_plans
                SET plan_json = ?, success_count = ?, failure_count = ?, avg_api_calls = ?, avg_duration_ms = ?, last_used_at = ?
                WHERE pattern_key = ?
                """,
                (json.dumps(plan), success_count, failure_count, avg_api_calls, avg_duration_ms, now, pattern_key),
            )
        self.conn.commit()

    def list_learned_plans(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM learned_plans ORDER BY last_used_at DESC").fetchall()
        out = []
        for row in rows:
            data = dict(row)
            data["plan"] = json.loads(data.pop("plan_json"))
            out.append(data)
        return out

    # ---------- Reporting helpers ----------

    def snapshot(self) -> dict[str, Any]:
        caps = self.list_capabilities()
        constraints = self.list_constraints()
        plans = self.list_learned_plans()
        runs = self.recent_runs(limit=5)
        return {
            "counts": {
                "capabilities": len(caps),
                "constraints": len(constraints),
                "learned_plans": len(plans),
                "recent_runs": len(runs),
            },
            "capabilities": [
                {
                    "name": c["name"],
                    "source": c["source"],
                    "success_count": c["success_count"],
                    "failure_count": c["failure_count"],
                    "avg_api_calls": c["avg_api_calls"],
                    "avg_duration_ms": c["avg_duration_ms"],
                }
                for c in caps
            ],
            "constraints": constraints,
            "learned_plans": [
                {
                    "pattern_key": p["pattern_key"],
                    "success_count": p["success_count"],
                    "failure_count": p["failure_count"],
                    "avg_api_calls": p["avg_api_calls"],
                    "avg_duration_ms": p["avg_duration_ms"],
                }
                for p in plans
            ],
            "recent_runs": runs,
        }

    def diff_snapshot(self, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        before_caps = {c["name"] for c in before.get("capabilities", [])}
        after_caps = {c["name"] for c in after.get("capabilities", [])}
        before_plans = {p["pattern_key"] for p in before.get("learned_plans", [])}
        after_plans = {p["pattern_key"] for p in after.get("learned_plans", [])}
        return {
            "new_capabilities": sorted(after_caps - before_caps),
            "new_learned_plans": sorted(after_plans - before_plans),
            "capability_count_delta": after["counts"]["capabilities"] - before["counts"]["capabilities"],
            "constraint_count_delta": after["counts"]["constraints"] - before["counts"]["constraints"],
        }

    def learning_stats(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT pattern_key, id, api_call_count, duration_ms, created_at
            FROM execution_runs
            WHERE status = 'success'
            ORDER BY pattern_key ASC, id ASC
            """
        ).fetchall()
        by_pattern: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_pattern.setdefault(row["pattern_key"], []).append(dict(row))
        stats = []
        for pattern, runs in by_pattern.items():
            if len(runs) < 2:
                continue
            first = runs[0]
            latest = runs[-1]
            call_delta = first["api_call_count"] - latest["api_call_count"]
            duration_delta = first["duration_ms"] - latest["duration_ms"]
            stats.append(
                {
                    "pattern_key": pattern,
                    "runs": len(runs),
                    "first_run_id": first["id"],
                    "latest_run_id": latest["id"],
                    "first_api_calls": first["api_call_count"],
                    "latest_api_calls": latest["api_call_count"],
                    "api_call_delta": call_delta,
                    "api_call_improvement_pct": round((call_delta / first["api_call_count"] * 100), 2) if first["api_call_count"] else 0,
                    "first_duration_ms": first["duration_ms"],
                    "latest_duration_ms": latest["duration_ms"],
                    "duration_delta_ms": duration_delta,
                }
            )
        return stats
