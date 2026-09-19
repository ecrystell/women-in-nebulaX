from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from app.domain.models import Scenario
from app.domain.preprocessing import require_prepared
from app.ingestion.csv_loader import load_instance
from app.solver.cp_sat import ScenarioASolver
from app.solver.policy import UnsupportedScenarioError, policy_for
from app.solver.scoring import scenario_a_score
from app.validation.preflight import validate_schedule


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DATA = ROOT / "data" / "public-instance"


def test_scenario_a_solves_public_instance_and_preserves_workload() -> None:
    instance = load_instance(PUBLIC_DATA)
    result = ScenarioASolver(time_limit_seconds=30).solve_with_diagnostics(instance)
    schedule = result.schedule

    assert result.diagnostics.status in {"FEASIBLE", "OPTIMAL"}
    assert schedule.scenario is Scenario.A
    assert len(schedule.access_assignments) == sum(
        activity.total_accesses for activity in instance.activities
    )
    assert all(assignment.eclo == 0 for assignment in schedule.access_assignments)
    assert scenario_a_score(instance, schedule) == result.diagnostics.weighted_score

    report = validate_schedule(require_prepared(instance), schedule)
    assert report.hard_violations == []
    assert report.status.value == "unverified"


def test_scenario_a_access_nights_are_local_and_within_contract_caps() -> None:
    instance = load_instance(PUBLIC_DATA)
    schedule = ScenarioASolver(time_limit_seconds=30).solve(instance)
    activities = {activity.activity_id: activity for activity in instance.activities}
    projects = {project.contract_number: project for project in instance.projects}
    nights: dict[tuple[str, str, int], set[int]] = defaultdict(set)
    for assignment in schedule.access_assignments:
        activity = activities[assignment.activity_id]
        project = projects[activity.contract_number]
        assert 1 <= assignment.access_night <= project.number_of_maximum_access_per_week
        nights[(activity.contract_number, activity.activity_type, assignment.week)].add(
            assignment.access_night
        )
    assert all(
        len(values) <= projects[contract].number_of_maximum_access_per_week
        for (contract, _activity_type, _week), values in nights.items()
    )


def test_scenario_b_still_fails_at_central_policy_boundary() -> None:
    try:
        policy_for(Scenario.B)
    except UnsupportedScenarioError as error:
        assert "Scenario B" in str(error)
        assert "Scenario C" in str(error)
    else:
        raise AssertionError("Scenario B must not be implemented in this workstream")
