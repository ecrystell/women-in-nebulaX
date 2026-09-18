"""Regression coverage for every locally observable PS1 hard-rule family."""

from __future__ import annotations

from pathlib import Path

from app.domain.models import AccessType, NatureOfWorks, Scenario
from app.ingestion.csv_loader import load_instance
from app.validation.adapter import ValidationStatus
from app.validation.preflight import _Preflight, load_submission, validate_schedule, validate_submission


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DATA = ROOT / "data" / "public-instance"
SAMPLE_SUBMISSION = PUBLIC_DATA / "sample-submission"


def bundle_copy():
    return load_instance(PUBLIC_DATA).model_copy(deep=True)


def schedule_copy():
    return load_submission(SAMPLE_SUBMISSION).model_copy(deep=True)


def rule_names(report) -> set[str]:
    return {str(violation["rule"]) for violation in report.hard_violations}


def test_published_sample_passes_observable_preflight_but_stays_unverified() -> None:
    report = validate_submission(PUBLIC_DATA, SAMPLE_SUBMISSION)

    assert report.status == ValidationStatus.UNVERIFIED
    assert report.feasible is None
    assert report.hard_violations == []
    assert report.detail["warnings"]
    assert "organiser validator" in report.message


def test_preflight_detects_workload_dates_precedence_and_topology_failures() -> None:
    workload = schedule_copy()
    workload.access_assignments = [item for item in workload.access_assignments if item.activity_id != "A001"]
    workload.occupancy_assignments = [item for item in workload.occupancy_assignments if item.activity_id != "A001"]
    assert "workload" in rule_names(validate_schedule(bundle_copy(), workload))

    early = schedule_copy()
    assignment = next(item for item in early.access_assignments if item.activity_id == "A001")
    old_week = assignment.week
    assignment.week = 1
    for occupancy in early.occupancy_assignments:
        if occupancy.activity_id == "A001" and occupancy.week == old_week:
            occupancy.week = 1
    assert "planned_date" in rule_names(validate_schedule(bundle_copy(), early))

    precedence = schedule_copy()
    assignment = next(item for item in precedence.access_assignments if item.activity_id == "A004")
    old_week = assignment.week
    assignment.week = 16
    for occupancy in precedence.occupancy_assignments:
        if occupancy.activity_id == "A004" and occupancy.week == old_week:
            occupancy.week = 16
    assert "precedence" in rule_names(validate_schedule(bundle_copy(), precedence))

    topology = schedule_copy()
    topology.occupancy_assignments.pop(0)
    assert "topology" in rule_names(validate_schedule(bundle_copy(), topology))


def test_preflight_detects_possession_mix_capacity_and_scenario_policies() -> None:
    mixed = schedule_copy()
    groups: dict[tuple[str, int, str], set[str]] = {}
    for occupancy in mixed.occupancy_assignments:
        groups.setdefault((occupancy.location_id, occupancy.week, occupancy.co_share_group), set()).add(occupancy.activity_id)
    (_, _, _), members = next(item for item in groups.items() if len(item[1]) >= 2)
    activity_id = next(iter(members))
    contract = next(activity.contract_number for activity in bundle_copy().activities if activity.activity_id == activity_id)
    mixed_bundle = bundle_copy()
    next(project for project in mixed_bundle.projects if project.contract_number == contract).access_type = AccessType.PM
    assert "mix" in rule_names(validate_schedule(mixed_bundle, mixed))

    capacity = schedule_copy()
    capacity_bundle = bundle_copy()
    occupied_location = capacity.occupancy_assignments[0].location_id
    next(supply for supply in capacity_bundle.location_supply if supply.location_id == occupied_location).supply_capacity = 0
    assert "capacity" in rule_names(validate_schedule(capacity_bundle, capacity))

    scenario_a = schedule_copy()
    scenario_a.access_assignments[0].eclo = 1
    assert "eclo" in rule_names(validate_schedule(bundle_copy(), scenario_a))

    scenario_b = schedule_copy()
    scenario_b.scenario = Scenario.B
    for result in scenario_b.contract_results:
        result.scenario = Scenario.B
    assert "planned_date" in rule_names(validate_schedule(bundle_copy(), scenario_b))

    scenario_c = schedule_copy()
    scenario_c.scenario = Scenario.C
    for result in scenario_c.contract_results:
        result.scenario = Scenario.C
    a001 = [item for item in scenario_c.access_assignments if item.activity_id == "A001"]
    a001[0].eclo, a001[0].week = 1, 1
    a001[1].eclo, a001[1].week = 1, 4
    assert "eclo" in rule_names(validate_schedule(bundle_copy(), scenario_c))


def test_preflight_detects_weekly_allocation_workfront_and_results_failures() -> None:
    allocation = schedule_copy()
    allocation_bundle = bundle_copy()
    allocation_by_activity = {
        activity_id: next(item for item in allocation.access_assignments if item.activity_id == activity_id)
        for activity_id in ("A001", "A002")
    }
    c001 = list(allocation_by_activity.values())
    c001[0].week, c001[0].access_night = 20, 1
    c001[1].week, c001[1].access_night = 20, 2
    next(project for project in allocation_bundle.projects if project.contract_number == "C001").number_of_maximum_access_per_week = 1
    assert "weekly_allocation" in rule_names(validate_schedule(allocation_bundle, allocation))

    workfront = schedule_copy()
    workfront_bundle = bundle_copy()
    workfront_by_activity = {
        activity_id: next(item for item in workfront.access_assignments if item.activity_id == activity_id)
        for activity_id in ("A001", "A002")
    }
    c001 = list(workfront_by_activity.values())
    c001[0].week = c001[1].week = 20
    c001[0].access_night = c001[1].access_night = 1
    next(project for project in workfront_bundle.projects if project.contract_number == "C001").number_of_workfronts = 1
    assert "workfront" in rule_names(validate_schedule(workfront_bundle, workfront))

    results = schedule_copy()
    results.contract_results[0].overrun_days += 1
    assert "results" in rule_names(validate_schedule(bundle_copy(), results))


def test_live_closure_footprint_derives_mirror_and_interchange_locations() -> None:
    bundle = bundle_copy()
    schedule = schedule_copy()
    checker = _Preflight(bundle, schedule)
    projects = {project.contract_number: project for project in bundle.projects}
    live_hub_activity = next(
        activity
        for activity in bundle.activities
        if projects[activity.contract_number].nature_of_activity == NatureOfWorks.LIVE
        and "H01_H02" in f"{activity.start_location_id},{activity.end_location_id}"
    )

    locations = checker.closure_locations(live_hub_activity)
    base = checker.base_locations(live_hub_activity)
    assert any(location.endswith(":EB") or location.endswith(":WB") for location in locations)
    assert any(location.split(":")[1] == "ALP" for location in locations)
    assert any(location.split(":")[1] == "BET" for location in locations)
    assert locations > base
