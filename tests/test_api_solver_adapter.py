"""Unit coverage for the API-facing A/B/C CP-SAT adapter boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.api.schemas import ScenarioChange
from app.api.solver_contract import SolverTimedOut
from app.domain.models import Scenario
from app.domain.preprocessing import prepare_instance
from app.ingestion.csv_loader import load_instance
from app.solver.adapter import API_SOLVE_TIME_LIMIT_SECONDS, CpSatSolverAdapter
from app.solver.cp_sat import SolveError
from app.validation.preflight import load_submission


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DATA = ROOT / "data" / "public-instance"
SOLVER_OUTPUT = ROOT / "solver_output"


def prepared_public_instance():
    result = prepare_instance(load_instance(PUBLIC_DATA))
    assert result.prepared is not None, result.findings
    return result.prepared


class FreshCandidateSolver:
    last_status = "OPTIMAL"
    last_wall_time_seconds = 1.25

    def __init__(self) -> None:
        self.calls: list[tuple[object, Scenario, object, object]] = []

    def solve_prepared(self, prepared, scenario, change=None, *, baseline=None):
        self.calls.append((prepared, scenario, change, baseline))
        return load_submission(SOLVER_OUTPUT / f"scenario_{scenario.value.lower()}")


class UnknownSolver:
    last_status = "UNKNOWN"
    last_wall_time_seconds = API_SOLVE_TIME_LIMIT_SECONDS

    def solve_prepared(self, prepared, scenario, change=None, *, baseline=None):
        raise SolveError("no candidate")


@pytest.mark.parametrize("scenario", [Scenario.A, Scenario.B, Scenario.C])
def test_adapter_passes_prepared_instance_to_each_delivered_scenario(
    monkeypatch: pytest.MonkeyPatch, scenario: Scenario
) -> None:
    prepared = prepared_public_instance()
    rail_solver = FreshCandidateSolver()
    adapter = CpSatSolverAdapter(time_limit_seconds=API_SOLVE_TIME_LIMIT_SECONDS)
    monkeypatch.setattr(adapter, "_new_solver", lambda: rail_solver)

    output = adapter.solve(prepared, scenario)

    assert output.schedule.scenario is scenario
    assert rail_solver.calls == [(prepared, scenario, None, None)]
    assert output.diagnostics is not None
    assert output.diagnostics.status == "OPTIMAL"
    assert output.diagnostics.time_limit_seconds == API_SOLVE_TIME_LIMIT_SECONDS


def test_adapter_maps_unknown_to_timeout_without_a_scenario_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = CpSatSolverAdapter(time_limit_seconds=API_SOLVE_TIME_LIMIT_SECONDS)
    monkeypatch.setattr(adapter, "_new_solver", lambda: UnknownSolver())

    with pytest.raises(SolverTimedOut, match="Scenario B"):
        adapter.solve(prepared_public_instance(), Scenario.B)

    assert adapter.last_diagnostics is not None
    assert adapter.last_diagnostics.status == "UNKNOWN"


def test_recovery_uses_valid_incumbent_only_when_no_c_candidate_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = CpSatSolverAdapter(time_limit_seconds=API_SOLVE_TIME_LIMIT_SECONDS)
    monkeypatch.setattr(adapter, "_new_solver", lambda: UnknownSolver())
    baseline = load_submission(SOLVER_OUTPUT / "scenario_c")
    change = ScenarioChange(
        change_id="test-recovery",
        base_schedule_id="baseline-c",
        scenario=Scenario.C,
        requested_by="test",
        confirmed_at=datetime.now(timezone.utc),
    )

    output = adapter.solve(prepared_public_instance(), Scenario.C, change, baseline)

    assert output.schedule == baseline
    assert output.diagnostics is not None
    assert output.diagnostics.recovery_source == "incumbent_fallback"


def test_adapter_defaults_to_and_caps_the_hosted_solve_budget() -> None:
    assert CpSatSolverAdapter().time_limit_seconds == API_SOLVE_TIME_LIMIT_SECONDS
    with pytest.raises(ValueError, match="at most 150 seconds"):
        CpSatSolverAdapter(time_limit_seconds=API_SOLVE_TIME_LIMIT_SECONDS + 0.1)
