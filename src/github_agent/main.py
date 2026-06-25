from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from .agent import GitHubIntelligenceAgent
from .config import Settings
from .github_client import GitHubClient
from .memory import AgentMemory

console = Console()


def build_agent() -> tuple[GitHubIntelligenceAgent, AgentMemory, GitHubClient, Settings]:
    settings = Settings.from_env()
    memory = AgentMemory(settings.memory_path)
    client = GitHubClient(settings)
    agent = GitHubIntelligenceAgent(memory, client, settings.report_dir)
    return agent, memory, client, settings


def cmd_setup(args: argparse.Namespace) -> None:
    agent, memory, client, settings = build_agent()
    inserted = agent.register_core_capabilities()
    repo = client.get_repo()
    console.print(Panel.fit("Setup complete", style="green"))
    console.print(f"Repository: [bold]{repo['full_name']}[/bold]")
    console.print(f"Memory DB: [bold]{settings.memory_path}[/bold]")
    console.print(f"Core capabilities newly registered: {inserted or 'none; already present'}")
    memory.close()


def cmd_seed(args: argparse.Namespace) -> None:
    agent, memory, client, settings = build_agent()
    agent.register_core_capabilities()
    result = client.create_demo_data()
    console.print(Panel.fit("Demo data ready", style="green"))
    console.print_json(json.dumps(result))
    console.print(f"API calls used: {client.api_calls}")
    memory.close()


def cmd_run(args: argparse.Namespace) -> None:
    agent, memory, client, settings = build_agent()
    report = agent.run(args.instruction)
    console.print(Panel.fit(f"Run #{report.run_id}: {report.status.value}", style="green" if report.status.value == "success" else "red"))
    console.print_json(json.dumps(report.model_dump(), indent=2))
    console.print(f"\nStructured report saved to: [bold]{settings.report_dir / f'run_{report.run_id}.json'}[/bold]")
    memory.close()


def cmd_memory(args: argparse.Namespace) -> None:
    agent, memory, client, settings = build_agent()
    agent.register_core_capabilities()
    snapshot = memory.snapshot()
    if args.json:
        console.print_json(json.dumps(snapshot, indent=2))
    else:
        console.print(Panel.fit("Persistent Memory Snapshot", style="cyan"))
        counts = snapshot["counts"]
        console.print(f"Capabilities: {counts['capabilities']} | Constraints: {counts['constraints']} | Learned plans: {counts['learned_plans']}")

        cap_table = Table(title="Capability Memory")
        cap_table.add_column("Name")
        cap_table.add_column("Source")
        cap_table.add_column("Success")
        cap_table.add_column("Failure")
        cap_table.add_column("Avg API Calls")
        for cap in snapshot["capabilities"]:
            cap_table.add_row(
                cap["name"],
                cap["source"],
                str(cap["success_count"]),
                str(cap["failure_count"]),
                f"{cap['avg_api_calls']:.2f}",
            )
        console.print(cap_table)

        plan_table = Table(title="Learned Plans")
        plan_table.add_column("Pattern")
        plan_table.add_column("Success")
        plan_table.add_column("Failure")
        plan_table.add_column("Avg API Calls")
        for plan in snapshot["learned_plans"]:
            plan_table.add_row(
                plan["pattern_key"],
                str(plan["success_count"]),
                str(plan["failure_count"]),
                f"{plan['avg_api_calls']:.2f}",
            )
        console.print(plan_table)

        run_table = Table(title="Recent Executions")
        run_table.add_column("Run")
        run_table.add_column("Pattern")
        run_table.add_column("Status")
        run_table.add_column("API Calls")
        run_table.add_column("Duration ms")
        for run in snapshot["recent_runs"]:
            run_table.add_row(str(run["id"]), run["pattern_key"], run["status"], str(run["api_call_count"]), str(run["duration_ms"]))
        console.print(run_table)
    memory.close()


def cmd_stats(args: argparse.Namespace) -> None:
    agent, memory, client, settings = build_agent()
    stats = memory.learning_stats()
    if args.json:
        console.print_json(json.dumps(stats, indent=2))
    else:
        console.print(Panel.fit("Measured Self-Learning", style="magenta"))
        if not stats:
            console.print("Run the same instruction pattern successfully at least twice to see learning metrics.")
        for row in stats:
            console.print(f"Pattern: [bold]{row['pattern_key']}[/bold]")
            console.print(f"Runs: {row['runs']}")
            console.print(f"First run API calls: {row['first_api_calls']} (run #{row['first_run_id']})")
            console.print(f"Latest run API calls: {row['latest_api_calls']} (run #{row['latest_run_id']})")
            console.print(f"API-call improvement: {row['api_call_improvement_pct']}%")
            console.print(f"First duration: {row['first_duration_ms']} ms | Latest duration: {row['latest_duration_ms']} ms")
            console.print("")
    memory.close()


def cmd_reset(args: argparse.Namespace) -> None:
    settings = Settings.from_env()
    if settings.memory_path.exists():
        settings.memory_path.unlink()
    console.print("Memory reset. Do not use this before the walkthrough demo.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autonomous GitHub Intelligence Agent")
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("setup", help="Initialize memory and validate GitHub access")
    setup.set_defaults(func=cmd_setup)

    seed = sub.add_parser("seed-demo-data", help="Create labels and demo issues in the configured repo")
    seed.set_defaults(func=cmd_seed)

    run = sub.add_parser("run", help="Run a natural language instruction")
    run.add_argument("instruction", help="Natural language instruction")
    run.set_defaults(func=cmd_run)

    mem = sub.add_parser("memory", help="Show persistent memory")
    mem.add_argument("--json", action="store_true", help="Output raw JSON")
    mem.set_defaults(func=cmd_memory)

    stats = sub.add_parser("stats", help="Show measured learning stats")
    stats.add_argument("--json", action="store_true", help="Output raw JSON")
    stats.set_defaults(func=cmd_stats)

    reset = sub.add_parser("reset-memory", help="Delete local SQLite memory for testing only")
    reset.set_defaults(func=cmd_reset)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
