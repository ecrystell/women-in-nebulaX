"""Fast Scenario C re-optimization for changed PS1 input packages.

The changed eight-CSV package is always authoritative.  The retained Scenario C
submission is used as a warm start and, optionally, as the source of confirmed
hard locks.  Only locally validated output is published.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from app.api.schemas import PlacementKey, ScenarioChange
from app.domain.models import ContractResult, InstanceBundle, Scenario, ScenarioSchedule
from app.exports.csv_writer import write_submission
from app.ingestion.csv_loader import load_instance
from app.solver.cp_sat import CpSatRailSolver, SolveError, SolverConfig
from app.validation.preflight import load_submission, validate_schedule, validate_submission


OFFICIAL_OUTPUTS = frozenset(
    {"SCHEDULE_ACCESS.csv", "SCHEDULE_OCCUPANCY.csv", "RESULTS.csv"}
)


class RecoveryError(RuntimeError):
    """Recovery cannot safely produce a validated three-file submission."""


@dataclass(frozen=True)
class RecoveryConfig:
    instance_dir: Path
    baseline_dir: Path
    output_dir: Path
    time_limit_seconds: float = 60.0
    workers: int = max(1, min(8, os.cpu_count() or 1))
    random_seed: int = 2026
    freeze_through_week: int = 0

    def __post_init__(self) -> None:
        if not 0 < self.time_limit_seconds <= 60:
            raise ValueError("recovery time limit must be greater than 0 and at most 60 seconds")
        if self.workers < 1:
            raise ValueError("workers must be at least 1")
        if self.freeze_through_week < 0:
            raise ValueError("freeze-through week cannot be negative")


def _horizon_start(instance: InstanceBundle) -> date:
    parameters = {item.key: item.value for item in instance.parameters}
    raw = parameters.get("horizon_start")
    if raw is None:
        raise RecoveryError("changed instance does not define horizon_start")
    try:
        return date.fromisoformat(raw)
    except ValueError as error:
        raise RecoveryError(f"changed instance has invalid horizon_start {raw!r}") from error


def refresh_results(instance: InstanceBundle, schedule: ScenarioSchedule) -> ScenarioSchedule:
    """Recalculate Scenario C result rows against the changed project dates.

    This does not repair access or occupancy rows.  It only prevents stale
    ``RESULTS.csv`` values from making an otherwise valid incumbent appear
    invalid after a deadline-only update.
    """

    horizon_start = _horizon_start(instance)
    known_activities = {item.activity_id: item for item in instance.activities}
    completion_week_by_contract: dict[str, int] = defaultdict(int)
    for assignment in schedule.access_assignments:
        activity = known_activities.get(assignment.activity_id)
        if activity is not None:
            completion_week_by_contract[activity.contract_number] = max(
                completion_week_by_contract[activity.contract_number], assignment.week
            )

    results: list[ContractResult] = []
    for project in instance.projects:
        completion_week = completion_week_by_contract.get(project.contract_number)
        completion = (
            horizon_start + timedelta(days=completion_week * 7 - 1)
            if completion_week
            else project.planned_completion_date
        )
        results.append(
            ContractResult(
                scenario=Scenario.C,
                contract_number=project.contract_number,
                simulated_completion_date=completion,
                overrun_days=max(0, (completion - project.planned_completion_date).days),
            )
        )
    return schedule.model_copy(update={"scenario": Scenario.C, "contract_results": results})


def _placement_signatures(schedule: ScenarioSchedule) -> dict[tuple[str, int], tuple[object, ...]]:
    occupancies: dict[tuple[str, int], list[tuple[str, str]]] = defaultdict(list)
    for row in schedule.occupancy_assignments:
        occupancies[row.activity_id, row.week].append((row.location_id, row.co_share_group))
    return {
        (row.activity_id, row.access_seq): (
            row.week,
            row.access_night,
            row.eclo,
            tuple(sorted(occupancies[row.activity_id, row.week])),
        )
        for row in schedule.access_assignments
    }


def _churn(before: ScenarioSchedule, after: ScenarioSchedule) -> dict[str, int]:
    old = _placement_signatures(before)
    new = _placement_signatures(after)
    keys = old.keys() | new.keys()
    unchanged = sum(1 for key in keys if key in old and key in new and old[key] == new[key])
    moved = sum(1 for key in keys if key in old and key in new and old[key] != new[key])
    return {
        "unchanged_placements": unchanged,
        "moved_placements": moved,
        "added_placements": sum(1 for key in keys if key not in old),
        "removed_placements": sum(1 for key in keys if key not in new),
    }


def _score(report) -> float:
    value = report.soft_scores.get("objective_score")
    if value is None:
        raise RecoveryError("local validator did not calculate objective_score")
    return float(value)


def _ensure_empty_output(output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RecoveryError(
            f"output directory must be new or empty so it contains exactly three CSVs: {output_dir}"
        )
    output_dir.parent.mkdir(parents=True, exist_ok=True)


def _publish_validated(
    instance_dir: Path, instance: InstanceBundle, schedule: ScenarioSchedule, output_dir: Path
) -> None:
    report = validate_schedule(instance, schedule)
    if report.hard_violations:
        raise RecoveryError(
            "refusing to export a schedule with local hard violations: "
            + "; ".join(str(item.get("detail", item)) for item in report.hard_violations[:5])
        )

    with tempfile.TemporaryDirectory(prefix="scenario-c-recovery-", dir=output_dir.parent) as raw:
        staging = Path(raw)
        write_submission(schedule, staging)
        emitted_report = validate_submission(instance_dir, staging)
        if emitted_report.hard_violations:
            raise RecoveryError("serialized recovery output failed local validation")
        if {path.name for path in staging.iterdir()} != OFFICIAL_OUTPUTS:
            raise RecoveryError("recovery writer did not emit exactly the three official CSVs")
        output_dir.mkdir(parents=True, exist_ok=True)
        for filename in sorted(OFFICIAL_OUTPUTS):
            shutil.move(str(staging / filename), str(output_dir / filename))


def run_reoptimization(
    config: RecoveryConfig,
    *,
    solver_factory: Callable[[SolverConfig], CpSatRailSolver] = CpSatRailSolver,
) -> dict[str, object]:
    """Run a bounded Scenario C recovery and return deterministic evidence."""

    _ensure_empty_output(config.output_dir)
    instance = load_instance(config.instance_dir)
    loaded_baseline = load_submission(config.baseline_dir)
    if loaded_baseline.scenario != Scenario.C:
        raise RecoveryError("baseline submission must be Scenario C")
    baseline = refresh_results(instance, loaded_baseline)
    baseline_report = validate_schedule(instance, baseline)
    baseline_valid = not baseline_report.hard_violations
    baseline_score = _score(baseline_report) if baseline_valid else None

    locked = [
        PlacementKey(activity_id=row.activity_id, access_seq=row.access_seq)
        for row in baseline.access_assignments
        if row.week <= config.freeze_through_week
    ]
    change = ScenarioChange(
        change_id="scenario-c-dynamic-update",
        base_schedule_id=str(config.baseline_dir),
        scenario=Scenario.C,
        locked_placements=locked,
        requested_by="scenario-c-recovery-cli",
        confirmed_at=datetime.now(timezone.utc) if locked else None,
        rationale=(
            f"Changed eight-CSV instance; retain confirmed work through week "
            f"{config.freeze_through_week}."
        ),
    )
    solver = solver_factory(
        SolverConfig(
            max_time_seconds=config.time_limit_seconds,
            workers=config.workers,
            random_seed=config.random_seed,
        )
    )

    candidate: ScenarioSchedule | None = None
    candidate_report = None
    solve_error: str | None = None
    try:
        candidate = solver.solve_bundle(instance, Scenario.C, change, baseline=baseline)
        candidate_report = validate_schedule(instance, candidate)
        if candidate_report.hard_violations:
            raise RecoveryError("CP-SAT candidate failed the fresh changed-instance validation gate")
    except SolveError as error:
        solve_error = str(error)

    selected_source: str
    if candidate is None:
        if not baseline_valid:
            raise RecoveryError(
                "recovery solver produced no schedule and the incumbent is invalid for the changed inputs: "
                + (solve_error or "unknown solver failure")
            )
        selected = baseline
        selected_report = baseline_report
        selected_source = "incumbent_fallback"
    else:
        candidate_score = _score(candidate_report)
        if baseline_valid and baseline_score is not None and baseline_score <= candidate_score:
            selected = baseline
            selected_report = baseline_report
            selected_source = "incumbent_not_worse"
        else:
            selected = candidate
            selected_report = candidate_report
            selected_source = "reoptimized"

    _publish_validated(config.instance_dir, instance, selected, config.output_dir)
    result_score = _score(selected_report)
    summary: dict[str, object] = {
        "scenario": "C",
        "validation_status": "unverified",
        "local_hard_violations": 0,
        "selected_source": selected_source,
        "solver_status": getattr(solver, "last_status", None),
        "solver_wall_time_seconds": getattr(solver, "last_wall_time_seconds", None),
        "solver_error": solve_error,
        "time_limit_seconds": config.time_limit_seconds,
        "locked_placements": len(locked),
        "baseline_valid_for_changed_instance": baseline_valid,
        "baseline_score": baseline_score,
        "result_score": result_score,
        "score_delta": result_score - baseline_score if baseline_score is not None else None,
        **_churn(baseline, selected),
        "output_dir": str(config.output_dir),
        "note": "Local checks passed; organiser validation of these exact files is still required.",
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-optimize a changed PS1 instance from the current Scenario C schedule."
    )
    parser.add_argument("--instance", type=Path, required=True, help="changed eight-CSV directory")
    parser.add_argument(
        "--baseline", type=Path, default=Path("solver_output/scenario_c"), help="current Scenario C submission"
    )
    parser.add_argument("--output", type=Path, required=True, help="new or empty output directory")
    parser.add_argument("--time-limit", type=float, default=60.0, help="seconds, capped at 60")
    parser.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 1)))
    parser.add_argument("--random-seed", type=int, default=2026)
    parser.add_argument(
        "--freeze-through-week",
        type=int,
        default=0,
        help="hard-lock all incumbent placements up to this confirmed week",
    )
    args = parser.parse_args()
    try:
        summary = run_reoptimization(
            RecoveryConfig(
                instance_dir=args.instance,
                baseline_dir=args.baseline,
                output_dir=args.output,
                time_limit_seconds=args.time_limit,
                workers=args.workers,
                random_seed=args.random_seed,
                freeze_through_week=args.freeze_through_week,
            )
        )
    except (OSError, ValueError, RecoveryError) as error:
        print(json.dumps({"scenario": "C", "status": "failed", "error": str(error)}, indent=2))
        return 2
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI.
    raise SystemExit(main())
