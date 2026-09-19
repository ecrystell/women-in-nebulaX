"""Command-line entry point for deterministic Scenario A/C runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..exports.csv_writer import write_submission
from ..domain.preprocessing import require_prepared
from ..ingestion.csv_loader import load_instance
from ..validation.preflight import SubmissionLoadError, load_submission, validate_schedule
from .cp_sat import ScenarioASolver, SolverError, SolverDependencyError
from .scenario_c import ScenarioCSolver
from .policy import UnsupportedScenarioError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Solve NEBULA X PS1 Scenario A or C.")
    parser.add_argument("--scenario", default="A", choices=["A", "C"], help="Implemented scenario.")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/public-instance"),
        help="Directory containing the eight official input CSVs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for the three generated submission CSVs (defaults to sample_submission/scenario_<scenario>).",
    )
    parser.add_argument("--time-limit", type=float, default=60.0)
    parser.add_argument("--random-seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=8)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        instance = load_instance(args.input_dir)
        prepared = require_prepared(instance)
        output_dir = args.output_dir or Path(f"sample_submission/scenario_{args.scenario.lower()}")
        initial_schedule = None
        initial_report = None
        try:
            loaded = load_submission(output_dir)
            loaded_report = validate_schedule(prepared, loaded)
            if loaded.scenario.value == args.scenario and not loaded_report.hard_violations:
                initial_schedule = loaded
                initial_report = loaded_report
        except (OSError, SubmissionLoadError, ValueError):
            pass
        if args.scenario == "A":
            solver = ScenarioASolver(
                time_limit_seconds=args.time_limit,
                random_seed=args.random_seed,
                num_search_workers=args.workers,
                initial_schedule=initial_schedule,
            )
        else:
            solver = ScenarioCSolver(
                time_limit_seconds=args.time_limit,
                random_seed=args.random_seed,
                num_search_workers=args.workers,
                initial_schedule=initial_schedule,
            )
        result = solver.solve_with_diagnostics(instance)
        selected_schedule = result.schedule
        retained_existing_incumbent = False
        if initial_schedule is not None and initial_report is not None:
            initial_score = float(initial_report.soft_scores.get("objective_score", float("inf")))
            candidate_key = (
                result.diagnostics.weighted_score,
                len(result.schedule.access_assignments),
            )
            initial_key = (
                initial_score,
                len(initial_schedule.access_assignments),
            )
            if initial_key <= candidate_key:
                selected_schedule = initial_schedule
                retained_existing_incumbent = True
        paths = write_submission(selected_schedule, output_dir)
        report = validate_schedule(prepared, selected_schedule)
    except (SolverError, SolverDependencyError, UnsupportedScenarioError, ValueError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, indent=2))
        return 2

    print(
        json.dumps(
            {
                "status": result.diagnostics.status,
                "objective_value_scaled": result.diagnostics.objective_value_scaled,
                "best_objective_bound_scaled": result.diagnostics.best_objective_bound_scaled,
                "relative_gap": result.diagnostics.relative_gap,
                "candidate_weighted_score": result.diagnostics.weighted_score,
                "weighted_score": report.soft_scores.get("objective_score"),
                "retained_existing_incumbent": retained_existing_incumbent,
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


if __name__ == "__main__":
    raise SystemExit(main())
