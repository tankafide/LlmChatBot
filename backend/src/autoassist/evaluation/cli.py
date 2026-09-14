import argparse
import asyncio
import json
from pathlib import Path

from autoassist.evaluation.runner import evaluate, load_labels


def main() -> None:
    """Validate the evaluation suite or explicitly run and save a live evaluation.

    Invoked by autoassist-evaluate. Without --live, print the case count and return None with
    no model calls. With --live, call the configured paid model, write a report, and raise
    SystemExit(0) for all checks passing or SystemExit(1) otherwise.
    Argument/configuration/file failures propagate.
    """
    parser = argparse.ArgumentParser(
        description="Evaluate real-model behavior on isolated imported inventory."
    )
    parser.add_argument("--suite", type=Path, default=Path("evaluations/conversations.json"))
    parser.add_argument("--config", type=Path, default=Path("config/dealerships.json"))
    parser.add_argument("--inventory", type=Path, default=Path("docs/context/inventory/data.csv"))
    parser.add_argument("--connection", default="primary-openai")
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--case", help="Run a single labeled conversation")
    parser.add_argument("--output", type=Path, default=Path("evaluation-results/report.json"))
    parser.add_argument("--live", action="store_true", help="Allow billed model requests")
    args = parser.parse_args()
    cases = load_labels(args.suite)
    if not args.live:
        print(
            f"Validated {len(cases)} labeled conversations. "
            "Use --live to call the configured model."
        )
        return
    report = asyncio.run(
        evaluate(args.config, args.inventory, args.suite, args.connection, args.repeats, args.case)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    raise SystemExit(0 if report["summary"]["automatic_pass_rate"] == 1 else 1)
