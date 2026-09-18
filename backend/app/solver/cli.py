"""Command-line entry point for a deterministic Scenario A run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..exports.csv_writer import write_submission
from ..ingestion.csv_loader import load_instance
from ..validation.preflight import validate_schedule
from .cp_sat import ScenarioASolver, SolverError, SolverDependencyError
from .policy import UnsupportedScenarioError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Solve NEBULA X PS1 Scenario A.")
    parser.add_argument("--scenario", default="A", choices=["A"], help="Implemented scenario.")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/public-instance"),
        help="Directory containing the eight official input CSVs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("sample_submission/scenario_a"),
        help="Directory for the three generated submission CSVs.",
    )
    parser.add_argument("--time-limit", type=float, default=60.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        instance = load_instance(args.input_dir)
        solver = ScenarioASolver(time_limit_seconds=args.time_limit)
        result = solver.solve_with_diagnostics(instance)
        paths = write_submission(result.schedule, args.output_dir)
        report = validate_schedule(instance, result.schedule)
    except (SolverError, SolverDependencyError, UnsupportedScenarioError, ValueError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, indent=2))
        return 2

    print(
        json.dumps(
            {
                "status": result.diagnostics.status,
                "objective_value_scaled": result.diagnostics.objective_value_scaled,
                "weighted_score": result.diagnostics.weighted_score,
                "solve_seconds": result.diagnostics.solve_seconds,
                "activities": result.diagnostics.activity_count,
                "scheduled_access_rows": result.diagnostics.scheduled_access_rows,
                "occupancy_rows": result.diagnostics.occupancy_rows,
                "contracts": result.diagnostics.contract_count,
                "local_preflight_hard_violations": len(report.hard_violations),
                "local_preflight_status": report.status.value,
                "outputs": {name: str(path) for name, path in paths.items()},
            },
            indent=2,
            default=str,
        )
    )
    return 0
