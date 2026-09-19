from __future__ import annotations

import csv
import shutil
from pathlib import Path

from app.domain.models import Scenario
from app.solver.cp_sat import SolveError
from app.solver.reoptimize_c import RecoveryConfig, run_reoptimization
from app.validation.preflight import validate_submission


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DATA = ROOT / "data" / "public-instance"
BASELINE = ROOT / "solver_output" / "scenario_c"


def _changed_instance(tmp_path: Path) -> Path:
    instance_dir = tmp_path / "changed-instance"
    shutil.copytree(PUBLIC_DATA, instance_dir)
    project_path = instance_dir / "07_PROJECT_DETAILS.csv"
    with project_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        headers = list(rows[0])
    # A deadline update proves that stale baseline RESULTS are refreshed from
    # the changed package before incumbent validation and selection.
    rows[0]["planned_completion_date"] = rows[0]["contract_completion_date"]
    with project_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return instance_dir


class _EchoSolver:
    last_status = "FEASIBLE"
    last_wall_time_seconds = 0.01
    received_change = None
    received_config = None

    def __init__(self, config) -> None:
        type(self).received_config = config

    def solve_bundle(self, instance, scenario, change, *, baseline):
        assert scenario == Scenario.C
        type(self).received_change = change
        return baseline


class _TimeoutSolver(_EchoSolver):
    last_status = "UNKNOWN"
    last_wall_time_seconds = 60.0

    def solve_bundle(self, instance, scenario, change, *, baseline):
        raise SolveError("CP-SAT returned UNKNOWN after 60.00s")


def test_recovery_uses_changed_instance_locks_and_exact_exports(tmp_path: Path) -> None:
    changed = _changed_instance(tmp_path)
    output = tmp_path / "recovered"
    summary = run_reoptimization(
        RecoveryConfig(
            instance_dir=changed,
            baseline_dir=BASELINE,
            output_dir=output,
            time_limit_seconds=12,
            workers=2,
            freeze_through_week=4,
        ),
        solver_factory=_EchoSolver,
    )

    assert {path.name for path in output.iterdir()} == {
        "SCHEDULE_ACCESS.csv",
        "SCHEDULE_OCCUPANCY.csv",
        "RESULTS.csv",
    }
    assert not validate_submission(changed, output).hard_violations
    assert summary["scenario"] == "C"
    assert summary["selected_source"] == "incumbent_not_worse"
    assert summary["local_hard_violations"] == 0
    assert summary["moved_placements"] == 0
    assert summary["locked_placements"] > 0
    assert len(_EchoSolver.received_change.locked_placements) == summary["locked_placements"]
    assert _EchoSolver.received_change.confirmed_at is not None
    assert _EchoSolver.received_config.max_time_seconds == 12


def test_recovery_safely_falls_back_to_valid_incumbent_on_unknown(tmp_path: Path) -> None:
    changed = _changed_instance(tmp_path)
    output = tmp_path / "fallback"
    summary = run_reoptimization(
        RecoveryConfig(
            instance_dir=changed,
            baseline_dir=BASELINE,
            output_dir=output,
            time_limit_seconds=60,
        ),
        solver_factory=_TimeoutSolver,
    )

    assert summary["selected_source"] == "incumbent_fallback"
    assert summary["solver_status"] == "UNKNOWN"
    assert "UNKNOWN" in summary["solver_error"]
    assert not validate_submission(changed, output).hard_violations
