"""Regression coverage for every locally observable PS1 hard-rule family."""

from __future__ import annotations

from pathlib import Path

from app.domain.models import AccessType, NatureOfWorks, OccupancyAssignment, Scenario
from app.domain.preprocessing import require_prepared
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


def finding_for(report, rule: str) -> dict[str, object]:
    return next(item for item in report.hard_violations if item["rule"] == rule)


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
    report = validate_schedule(require_prepared(bundle_copy()), workload)
    finding = finding_for(report, "workload")
    assert finding["derived_footprint"]
    assert finding["input_values"] == {"delivered_access_units": 0, "required_access_units": 2}

    early = schedule_copy()
    assignment = next(item for item in early.access_assignments if item.activity_id == "A001")
    old_week = assignment.week
    assignment.week = 1
    for occupancy in early.occupancy_assignments:
        if occupancy.activity_id == "A001" and occupancy.week == old_week:
            occupancy.week = 1
    report = validate_schedule(require_prepared(bundle_copy()), early)
    finding = finding_for(report, "planned_date")
    assert finding["input_values"]["planned_start_week"] > finding["input_values"]["actual_first_week"]

    precedence = schedule_copy()
    assignment = next(item for item in precedence.access_assignments if item.activity_id == "A004")
    old_week = assignment.week
    assignment.week = 16
    for occupancy in precedence.occupancy_assignments:
        if occupancy.activity_id == "A004" and occupancy.week == old_week:
            occupancy.week = 16
    report = validate_schedule(require_prepared(bundle_copy()), precedence)
    finding = finding_for(report, "precedence")
    assert finding["input_values"]["successor_first_week"] <= finding["input_values"]["predecessor_last_week"]

    topology = schedule_copy()
    topology.occupancy_assignments.pop(0)
    report = validate_schedule(require_prepared(bundle_copy()), topology)
    finding = finding_for(report, "topology")
    assert finding["derived_footprint"]
    assert finding["input_values"] == {
        "expected_location_count": len(finding["derived_footprint"]),
        "observed_location_count": len(finding["derived_footprint"]) - 1,
        "missing_location_count": 1,
        "unexpected_location_count": 0,
    }


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
    report = validate_schedule(require_prepared(mixed_bundle), mixed)
    finding = finding_for(report, "mix")
    assert finding["co_share_group"]
    assert finding["derived_footprint"]
    assert finding["input_values"]["pm_count"] == 1

    capacity = schedule_copy()
    capacity_bundle = bundle_copy()
    occupied_location = capacity.occupancy_assignments[0].location_id
    next(supply for supply in capacity_bundle.location_supply if supply.location_id == occupied_location).supply_capacity = 0
    report = validate_schedule(require_prepared(capacity_bundle), capacity)
    finding = finding_for(report, "capacity")
    assert finding["input_values"]["supply_capacity"] == 0
    assert finding["input_values"]["possession_group_count"] > 0

    scenario_a = schedule_copy()
    scenario_a.access_assignments[0].eclo = 1
    report = validate_schedule(require_prepared(bundle_copy()), scenario_a)
    finding = finding_for(report, "eclo")
    assert finding["input_values"] == {"scenario": "A", "eclo": 1}
    assert finding["derived_footprint"]

    scenario_b = schedule_copy()
    scenario_b.scenario = Scenario.B
    for result in scenario_b.contract_results:
        result.scenario = Scenario.B
    report = validate_schedule(require_prepared(bundle_copy()), scenario_b)
    finding = finding_for(report, "planned_date")
    assert finding["input_values"]["scenario"] == "B"

    scenario_c = schedule_copy()
    scenario_c.scenario = Scenario.C
    for result in scenario_c.contract_results:
        result.scenario = Scenario.C
    a001 = [item for item in scenario_c.access_assignments if item.activity_id == "A001"]
    a001[0].eclo, a001[0].week = 1, 1
    a001[1].eclo, a001[1].week = 1, 4
    assert "eclo" in rule_names(validate_schedule(require_prepared(bundle_copy()), scenario_c))


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
    report = validate_schedule(require_prepared(allocation_bundle), allocation)
    finding = finding_for(report, "weekly_allocation")
    assert finding["input_values"]["distinct_access_nights"] == 2
    assert finding["input_values"]["maximum_access_per_week"] == 1

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
    report = validate_schedule(require_prepared(workfront_bundle), workfront)
    finding = finding_for(report, "workfront")
    assert finding["input_values"]["access_night"] == 1
    assert finding["input_values"]["workfront_limit"] == 1

    results = schedule_copy()
    results.contract_results[0].overrun_days += 1
    report = validate_schedule(require_prepared(bundle_copy()), results)
    finding = finding_for(report, "results")
    assert finding["input_values"]["reported_overrun_days"] != finding["input_values"]["expected_overrun_days"]


def test_cross_line_live_eclo_evidence_covers_both_affected_lines() -> None:
    bundle = bundle_copy()
    schedule = schedule_copy()
    schedule.scenario = Scenario.C
    for result in schedule.contract_results:
        result.scenario = Scenario.C
    projects = {project.contract_number: project for project in bundle.projects}
    live = next(
        activity
        for activity in bundle.activities
        if projects[activity.contract_number].nature_of_activity == NatureOfWorks.LIVE
        and "H01_H02" in f"{activity.start_location_id},{activity.end_location_id}"
    )
    access = next(item for item in schedule.access_assignments if item.activity_id == live.activity_id)
    original_week = access.week
    access.week, access.eclo = 1, 1
    original_occupancies = [
        item for item in schedule.occupancy_assignments
        if item.activity_id == live.activity_id and item.week == original_week
    ]
    for occupancy in original_occupancies:
        occupancy.week = 1
    duplicate_access = access.model_copy(deep=True)
    duplicate_access.access_seq, duplicate_access.week, duplicate_access.eclo = 2, 4, 1
    schedule.access_assignments.append(duplicate_access)
    for occupancy in original_occupancies:
        duplicate_occupancy = occupancy.model_copy(deep=True)
        duplicate_occupancy.week = 4
        schedule.occupancy_assignments.append(duplicate_occupancy)

    report = validate_schedule(require_prepared(bundle), schedule)
    eclo_findings = [
        item for item in report.hard_violations
        if item["rule"] == "eclo" and item.get("input_values", {}).get("scenario") == "C"
    ]

    assert {item["input_values"]["affected_line"] for item in eclo_findings} == {"ALP", "BET"}
    assert all(item["derived_footprint"] for item in eclo_findings)


def test_local_score_components_are_stable_for_the_public_fixture() -> None:
    report = validate_schedule(require_prepared(bundle_copy()), schedule_copy())

    assert report.soft_scores["overrun_days_total"] == 28
    assert report.soft_scores["priority_overrun"] == {"1": 0, "2": 0, "3": 28}
    assert report.soft_scores["priority_weighted_score"] == 48.3
    assert report.soft_scores["objective_score"] == 48.3


def test_scenario_b_and_c_capacity_and_eclo_metrics_use_published_weights() -> None:
    scenario_b = schedule_copy()
    scenario_b.scenario = Scenario.B
    for result in scenario_b.contract_results:
        result.scenario = Scenario.B
    scenario_b.access_assignments[0].eclo = 1
    bundle_b = bundle_copy()
    b_location = scenario_b.occupancy_assignments[0].location_id
    for supply in bundle_b.location_supply:
        if supply.location_id == b_location:
            supply.supply_capacity = 0
    b_report = validate_schedule(require_prepared(bundle_b), scenario_b)
    b_scores = b_report.soft_scores
    assert b_scores["excess_access_nights_total"] >= 1
    assert b_scores["eclo_nights_total"] >= 1
    assert b_scores["objective_score"] == 7 * b_scores["excess_access_nights_total"] + 5 * b_scores["eclo_nights_total"]

    scenario_c = schedule_copy()
    scenario_c.scenario = Scenario.C
    for result in scenario_c.contract_results:
        result.scenario = Scenario.C
    bundle_c = bundle_copy()
    location = ""
    week = 0
    second_activity = ""
    for occupancy in scenario_c.occupancy_assignments:
        groups = {
            item.co_share_group
            for item in scenario_c.occupancy_assignments
            if item.location_id == occupancy.location_id and item.week == occupancy.week
        }
        candidate = next(
            (
                assignment.activity_id
                for assignment in scenario_c.access_assignments
                if assignment.week == occupancy.week and assignment.activity_id != occupancy.activity_id
            ),
            None,
        )
        if len(groups) == 1 and candidate:
            location, week, second_activity = occupancy.location_id, occupancy.week, candidate
            break
    assert location and week and second_activity
    for supply in bundle_c.location_supply:
        if supply.location_id == location:
            supply.supply_capacity = 0
    c_boundary_report = validate_schedule(require_prepared(bundle_c), scenario_c)
    assert not any(
        item["rule"] == "capacity" and location in item.get("location_ids", []) and item.get("week") == week
        for item in c_boundary_report.hard_violations
    )
    scenario_c.occupancy_assignments.append(
        OccupancyAssignment(
            activity_id=second_activity,
            week=week,
            location_id=location,
            co_share_group="r42c-extra",
        )
    )
    c_report = validate_schedule(require_prepared(bundle_c), scenario_c)
    finding = finding_for(c_report, "capacity")
    assert finding["week"] == week
    assert finding["input_values"] == {
        "possession_group_count": 2,
        "supply_capacity": 0,
        "allowed_possessions": 1,
    }
    c_scores = c_report.soft_scores
    assert c_scores["objective_score"] == (
        c_scores["priority_weighted_score"]
        + 7 * c_scores["excess_access_nights_total"]
        + 5 * c_scores["eclo_nights_total"]
    )


def test_live_closure_footprint_derives_mirror_and_interchange_locations() -> None:
    bundle = bundle_copy()
    schedule = schedule_copy()
    checker = _Preflight(require_prepared(bundle), schedule)
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
