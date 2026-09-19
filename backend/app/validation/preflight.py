"""Deterministic local preflight checks for PS1 submission CSVs.

This module deliberately has a narrower authority than the organiser validator.
It catches the published rules we can reproduce from the brief, reports every
finding as evidence, and *always* returns an ``unverified`` report.  A clean
preflight is therefore a reason to spend an organiser submission, never a
feasibility claim.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, ValidationError

from app.domain.models import (
    AccessAssignment,
    ActivityRecord,
    ContractResult,
    OccupancyAssignment,
    Scenario,
    ScenarioSchedule,
)
from app.domain.preprocessing import PreparedInstance, PreparationFinding, prepare_instance
from app.exports.csv_writer import ACCESS_HEADERS, OCCUPANCY_HEADERS, RESULT_HEADERS
from app.ingestion.csv_loader import load_instance
from app.validation.adapter import OfficialValidatorAdapter, ValidationReport


SUBMISSION_TABLES: dict[str, tuple[type[BaseModel], list[str]]] = {
    "SCHEDULE_ACCESS.csv": (AccessAssignment, ACCESS_HEADERS),
    "SCHEDULE_OCCUPANCY.csv": (OccupancyAssignment, OCCUPANCY_HEADERS),
    "RESULTS.csv": (ContractResult, RESULT_HEADERS),
}


class SubmissionLoadError(ValueError):
    """A submission does not meet the published three-CSV contract."""


def _load_submission_table(path: Path, model: type[BaseModel], headers: list[str]) -> list[BaseModel]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != headers:
            raise SubmissionLoadError(
                f"{path.name}: expected headers {headers}, received {reader.fieldnames}"
            )
        rows: list[BaseModel] = []
        for row_number, row in enumerate(reader, start=2):
            try:
                rows.append(model.model_validate(row))
            except ValidationError as error:
                raise SubmissionLoadError(f"{path.name}: row {row_number}: {error}") from error
    return rows


def load_submission(submission_dir: Path) -> ScenarioSchedule:
    """Load exactly the official answer-key files with exact headers and types."""

    missing = [name for name in SUBMISSION_TABLES if not (submission_dir / name).is_file()]
    unexpected = [path.name for path in submission_dir.glob("*.csv") if path.name not in SUBMISSION_TABLES]
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append(f"missing {missing}")
        if unexpected:
            details.append(f"unexpected {unexpected}")
        raise SubmissionLoadError("submission must contain exactly three CSVs: " + "; ".join(details))

    access = _load_submission_table(submission_dir / "SCHEDULE_ACCESS.csv", *SUBMISSION_TABLES["SCHEDULE_ACCESS.csv"])
    occupancy = _load_submission_table(
        submission_dir / "SCHEDULE_OCCUPANCY.csv", *SUBMISSION_TABLES["SCHEDULE_OCCUPANCY.csv"]
    )
    results = _load_submission_table(submission_dir / "RESULTS.csv", *SUBMISSION_TABLES["RESULTS.csv"])
    scenarios = {result.scenario for result in results if isinstance(result, ContractResult)}
    if len(scenarios) != 1:
        raise SubmissionLoadError("RESULTS.csv must contain exactly one scenario")
    return ScenarioSchedule(
        scenario=scenarios.pop(),
        access_assignments=[row for row in access if isinstance(row, AccessAssignment)],
        occupancy_assignments=[row for row in occupancy if isinstance(row, OccupancyAssignment)],
        contract_results=[row for row in results if isinstance(row, ContractResult)],
    )


class _Preflight:
    def __init__(self, prepared: PreparedInstance, schedule: ScenarioSchedule) -> None:
        self.prepared = prepared
        self.instance = prepared.instance
        self.schedule = schedule
        self.violations: list[dict[str, object]] = []
        self.projects = prepared.projects
        self.activities = {item.activity.activity_id: item.activity for item in prepared.activities}
        self.prepared_activities = prepared.activities_by_id
        self.supply = prepared.supply
        self.horizon_weeks = prepared.calendar.horizon_weeks
        self.warnings: list[str] = []

    def add(
        self,
        rule: str,
        detail: str,
        *,
        activity_ids: Iterable[str] | None = None,
        location_ids: Iterable[str] | None = None,
        week: int | None = None,
        co_share_group: str | None = None,
        derived_footprint: Iterable[str] | None = None,
        input_values: dict[str, str | int | float | bool | None] | None = None,
    ) -> None:
        violation: dict[str, object] = {"rule": rule, "severity": "hard", "detail": detail}
        if activity_ids:
            violation["activity_ids"] = sorted(set(activity_ids))
        if location_ids:
            violation["location_ids"] = sorted(set(location_ids))
        if week:
            violation["week"] = week
        if co_share_group:
            violation["co_share_group"] = co_share_group
        if derived_footprint:
            violation["derived_footprint"] = sorted(set(derived_footprint))
        if input_values:
            violation["input_values"] = input_values
        self.violations.append(violation)

    def base_locations(self, activity: ActivityRecord) -> set[str]:
        return set(self.prepared_activities[activity.activity_id].base_locations)

    def closure_locations(self, activity: ActivityRecord) -> set[str]:
        return set(self.prepared_activities[activity.activity_id].closure_locations)

    def week_end(self, week: int) -> date | None:
        return self.prepared.calendar.week_end(week)

    def planned_week(self, value: date) -> int | None:
        return self.prepared.calendar.planned_week(value)

    def validate_schedule_shape(self) -> tuple[dict[tuple[str, int], dict[str, str]], dict[str, list[AccessAssignment]]]:
        accesses_by_activity: dict[str, list[AccessAssignment]] = defaultdict(list)
        accesses_by_activity_week: dict[tuple[str, int], list[AccessAssignment]] = defaultdict(list)
        for assignment in self.schedule.access_assignments:
            accesses_by_activity[assignment.activity_id].append(assignment)
            accesses_by_activity_week[(assignment.activity_id, assignment.week)].append(assignment)
            if assignment.activity_id not in self.activities:
                self.add("schedule_access", f"Unknown activity {assignment.activity_id} in SCHEDULE_ACCESS.csv.", activity_ids=[assignment.activity_id], week=assignment.week)
            if self.horizon_weeks and assignment.week > self.horizon_weeks:
                self.add("schedule_access", f"Week {assignment.week} is outside the {self.horizon_weeks}-week horizon.", activity_ids=[assignment.activity_id], week=assignment.week)

        for activity_id, assignments in accesses_by_activity.items():
            sequences = [assignment.access_seq for assignment in assignments]
            if len(sequences) != len(set(sequences)) or set(sequences) != set(range(1, len(sequences) + 1)):
                self.add("schedule_access", f"{activity_id} access_seq values must be unique and contiguous from 1.", activity_ids=[activity_id])
        for (activity_id, week), assignments in accesses_by_activity_week.items():
            if len(assignments) > 1:
                self.add("schedule_access", f"{activity_id} has more than one access in week {week}.", activity_ids=[activity_id], week=week)

        groups_by_activity_week: dict[tuple[str, int], dict[str, str]] = defaultdict(dict)
        occupancy_seen: set[tuple[str, int, str]] = set()
        for occupancy in self.schedule.occupancy_assignments:
            key = (occupancy.activity_id, occupancy.week, occupancy.location_id)
            if key in occupancy_seen:
                self.add("schedule_occupancy", f"Duplicate occupancy for {occupancy.activity_id} at {occupancy.location_id}.", activity_ids=[occupancy.activity_id], location_ids=[occupancy.location_id], week=occupancy.week)
            occupancy_seen.add(key)
            if not occupancy.co_share_group:
                self.add("schedule_occupancy", "co_share_group must not be empty.", activity_ids=[occupancy.activity_id], location_ids=[occupancy.location_id], week=occupancy.week)
            if occupancy.activity_id not in self.activities:
                self.add("schedule_occupancy", f"Unknown activity {occupancy.activity_id} in SCHEDULE_OCCUPANCY.csv.", activity_ids=[occupancy.activity_id], location_ids=[occupancy.location_id], week=occupancy.week)
            if occupancy.location_id not in self.supply:
                self.add("schedule_occupancy", f"Unknown location {occupancy.location_id} in SCHEDULE_OCCUPANCY.csv.", activity_ids=[occupancy.activity_id], location_ids=[occupancy.location_id], week=occupancy.week)
            if (occupancy.activity_id, occupancy.week) not in accesses_by_activity_week:
                self.add("schedule_occupancy", f"{occupancy.activity_id} has occupancy in week {occupancy.week} without an access assignment.", activity_ids=[occupancy.activity_id], location_ids=[occupancy.location_id], week=occupancy.week)
            groups_by_activity_week[(occupancy.activity_id, occupancy.week)][occupancy.location_id] = occupancy.co_share_group

        for key in accesses_by_activity_week:
            activity_id, week = key
            activity = self.activities.get(activity_id)
            if not activity:
                continue
            expected = self.base_locations(activity)
            actual = set(groups_by_activity_week[key])
            missing, extra = expected - actual, actual - expected
            if missing or extra:
                parts = []
                if missing:
                    parts.append(f"missing {sorted(missing)}")
                if extra:
                    parts.append(f"unexpected {sorted(extra)}")
                self.add(
                    "topology",
                    f"{activity_id} occupancy footprint is invalid: {'; '.join(parts)}.",
                    activity_ids=[activity_id],
                    location_ids=expected | actual,
                    week=week,
                    derived_footprint=expected,
                    input_values={
                        "expected_location_count": len(expected),
                        "observed_location_count": len(actual),
                        "missing_location_count": len(missing),
                        "unexpected_location_count": len(extra),
                    },
                )
        return groups_by_activity_week, accesses_by_activity

    def validate_workload_dates_and_precedence(self, accesses_by_activity: dict[str, list[AccessAssignment]]) -> None:
        first_week: dict[str, int] = {}
        last_week: dict[str, int] = {}
        for activity in self.instance.activities:
            assignments = accesses_by_activity.get(activity.activity_id, [])
            yield_total = sum(1.5 if assignment.eclo else 1.0 for assignment in assignments)
            if yield_total < activity.total_accesses:
                self.add(
                    "workload",
                    f"{activity.activity_id} delivers {yield_total:g} of required {activity.total_accesses:g} access units.",
                    activity_ids=[activity.activity_id],
                    derived_footprint=self.closure_locations(activity),
                    input_values={"delivered_access_units": yield_total, "required_access_units": activity.total_accesses},
                )
            if not assignments:
                continue
            first_week[activity.activity_id] = min(item.week for item in assignments)
            last_week[activity.activity_id] = max(item.week for item in assignments)
            planned_week = self.planned_week(activity.planned_start_date)
            if planned_week and first_week[activity.activity_id] < planned_week:
                self.add(
                    "planned_date",
                    f"{activity.activity_id} starts in week {first_week[activity.activity_id]} before planned week {planned_week}.",
                    activity_ids=[activity.activity_id],
                    week=first_week[activity.activity_id],
                    derived_footprint=self.closure_locations(activity),
                    input_values={
                        "planned_start_date": activity.planned_start_date.isoformat(),
                        "planned_start_week": planned_week,
                        "actual_first_week": first_week[activity.activity_id],
                    },
                )
        for activity in self.instance.activities:
            predecessor = activity.predecessor_activity_id
            if predecessor and predecessor in last_week and activity.activity_id in first_week and first_week[activity.activity_id] <= last_week[predecessor]:
                self.add(
                    "precedence",
                    f"{activity.activity_id} starts in week {first_week[activity.activity_id]} before predecessor {predecessor} finishes in week {last_week[predecessor]}.",
                    activity_ids=[predecessor, activity.activity_id],
                    week=first_week[activity.activity_id],
                    derived_footprint=self.closure_locations(activity),
                    input_values={"predecessor_last_week": last_week[predecessor], "successor_first_week": first_week[activity.activity_id]},
                )

    def validate_mixes_capacity_and_closures(self, groups_by_activity_week: dict[tuple[str, int], dict[str, str]]) -> dict[tuple[str, int], int]:
        possession_members: dict[tuple[str, int, str], set[str]] = defaultdict(set)
        base_occupants: dict[tuple[str, int], list[tuple[str, str]]] = defaultdict(list)
        for (activity_id, week), locations in groups_by_activity_week.items():
            for location_id, group in locations.items():
                possession_members[(location_id, week, group)].add(activity_id)
                base_occupants[(location_id, week)].append((activity_id, group))

        possession_count: dict[tuple[str, int], int] = defaultdict(int)
        for (location_id, week, group), members in possession_members.items():
            possession_count[(location_id, week)] += 1
            types = [self.projects[self.activities[activity_id].contract_number].access_type.value for activity_id in members if activity_id in self.activities and self.activities[activity_id].contract_number in self.projects]
            pm, pc, coworker = types.count("PM"), types.count("PC"), types.count("C")
            legal = (pm == 1 and len(types) == 1) or (pm == 0 and pc == 1 and coworker <= 3 and len(types) == pc + coworker) or (pm == 0 and pc == 0 and 1 <= coworker <= 4)
            if not legal:
                footprint = set().union(
                    *(self.closure_locations(self.activities[activity_id]) for activity_id in members if activity_id in self.activities)
                )
                self.add(
                    "mix",
                    f"Illegal possession mix at {location_id}, week {week}, group {group}: {types}.",
                    activity_ids=members,
                    location_ids=[location_id],
                    week=week,
                    co_share_group=group,
                    derived_footprint=footprint,
                    input_values={"pm_count": pm, "pc_count": pc, "c_count": coworker, "member_count": len(types)},
                )

        for (location_id, week), count in possession_count.items():
            capacity = self.supply.get(location_id, 0)
            allowed = capacity if self.schedule.scenario in {Scenario.A, Scenario.B} else capacity + 1
            if self.schedule.scenario == Scenario.A and count > allowed:
                self.add(
                    "capacity",
                    f"{location_id} has {count} possessions in week {week}; Scenario A capacity is {capacity}.",
                    location_ids=[location_id],
                    week=week,
                    input_values={"possession_group_count": count, "supply_capacity": capacity, "allowed_possessions": allowed},
                )
            elif self.schedule.scenario == Scenario.C and count > allowed:
                self.add(
                    "capacity",
                    f"{location_id} has {count} possessions in week {week}; Scenario C limit is supply {capacity} + 1.",
                    location_ids=[location_id],
                    week=week,
                    input_values={"possession_group_count": count, "supply_capacity": capacity, "allowed_possessions": allowed},
                )

        # We expand buffer, opposite-bound, and H01/H02 Live footprints above so
        # the solver has one deterministic source of derived locations.  The
        # published submission schema, however, has no global time-slot or
        # ordering field with which to compare *different* possession groups:
        # access_night is contract-local and co_share_group is location-local.
        # Declaring those separate groups concurrent would incorrectly reject the
        # organiser's published feasible sample.  Keep this limitation explicit
        # rather than inventing a closure rule the CSVs cannot evidence.
        if groups_by_activity_week:
            self.warnings.append(
                "Closure footprints (buffers, Live mirroring, and H01/H02 crossover) are expanded locally, "
                "but cross-group closure ordering cannot be proved from the published three CSVs. "
                "The organiser validator remains authoritative for that hard rule."
            )
        return possession_count

    def validate_allocation_and_eclo(self, accesses_by_activity: dict[str, list[AccessAssignment]]) -> None:
        by_contract_type_week: dict[tuple[str, str, int], list[AccessAssignment]] = defaultdict(list)
        eclo_weeks_by_line: dict[str, set[int]] = defaultdict(set)
        eclo_footprints_by_line: dict[str, set[str]] = defaultdict(set)
        for activity_id, assignments in accesses_by_activity.items():
            activity = self.activities.get(activity_id)
            if not activity or activity.contract_number not in self.projects:
                continue
            project = self.projects[activity.contract_number]
            for assignment in assignments:
                by_contract_type_week[(activity.contract_number, activity.activity_type, assignment.week)].append(assignment)
                if self.schedule.scenario == Scenario.A and assignment.eclo:
                    self.add(
                        "eclo",
                        f"Scenario A forbids ECLO ({activity_id}, week {assignment.week}).",
                        activity_ids=[activity_id],
                        week=assignment.week,
                        derived_footprint=self.closure_locations(activity),
                        input_values={"scenario": "A", "eclo": 1},
                    )
                if self.schedule.scenario == Scenario.C and assignment.eclo:
                    footprint = self.closure_locations(activity)
                    lines = {location.split(":")[1] for location in footprint}
                    for line in lines:
                        eclo_weeks_by_line[line].add(assignment.week)
                        eclo_footprints_by_line[line].update(footprint)
        for (contract, activity_type, week), assignments in by_contract_type_week.items():
            project = self.projects[contract]
            nights = {assignment.access_night for assignment in assignments}
            if len(nights) > project.number_of_maximum_access_per_week:
                self.add(
                    "weekly_allocation",
                    f"{contract}/{activity_type} uses {len(nights)} access nights in week {week}; cap is {project.number_of_maximum_access_per_week}.",
                    activity_ids=[assignment.activity_id for assignment in assignments],
                    week=week,
                    input_values={"contract_number": contract, "activity_type": activity_type, "distinct_access_nights": len(nights), "maximum_access_per_week": project.number_of_maximum_access_per_week},
                )
            for night in nights:
                activity_ids = {assignment.activity_id for assignment in assignments if assignment.access_night == night}
                if len(activity_ids) > project.number_of_workfronts:
                    self.add(
                        "workfront",
                        f"{contract}/{activity_type} runs {len(activity_ids)} activities on access night {night} in week {week}; workfront cap is {project.number_of_workfronts}.",
                        activity_ids=activity_ids,
                        week=week,
                        input_values={"contract_number": contract, "activity_type": activity_type, "access_night": night, "activity_count": len(activity_ids), "workfront_limit": project.number_of_workfronts},
                    )
        for line, weeks in eclo_weeks_by_line.items():
            if weeks and max(weeks) - min(weeks) + 1 > 2:
                self.add(
                    "eclo",
                    f"Scenario C ECLO on line {line} spans weeks {min(weeks)} to {max(weeks)}; maximum continuous window is two weeks.",
                    week=min(weeks),
                    derived_footprint=eclo_footprints_by_line[line],
                    input_values={"scenario": "C", "affected_line": line, "first_eclo_week": min(weeks), "last_eclo_week": max(weeks), "window_weeks": max(weeks) - min(weeks) + 1, "maximum_window_weeks": 2},
                )

    def validate_results(self, accesses_by_activity: dict[str, list[AccessAssignment]], possession_count: dict[tuple[str, int], int]) -> dict[str, object]:
        results_by_contract: dict[str, ContractResult] = {}
        for result in self.schedule.contract_results:
            if result.contract_number in results_by_contract:
                self.add("results", f"Duplicate RESULTS row for contract {result.contract_number}.")
            results_by_contract[result.contract_number] = result
            if result.scenario != self.schedule.scenario:
                self.add("results", f"RESULTS row for {result.contract_number} has a mixed scenario.")
        for contract in self.projects:
            if contract not in results_by_contract:
                self.add("results", f"Missing RESULTS row for contract {contract}.")
        for contract in results_by_contract:
            if contract not in self.projects:
                self.add("results", f"RESULTS contains unknown contract {contract}.")

        completion_by_activity: dict[str, date] = {}
        for activity_id, assignments in accesses_by_activity.items():
            if assignments:
                completion = self.week_end(max(assignment.week for assignment in assignments))
                if completion:
                    completion_by_activity[activity_id] = completion
        completion_by_contract: dict[str, date] = {}
        for activity in self.instance.activities:
            completion = completion_by_activity.get(activity.activity_id)
            if completion:
                current = completion_by_contract.get(activity.contract_number)
                completion_by_contract[activity.contract_number] = max(current, completion) if current else completion
        priority_overrun: dict[str, int] = {"1": 0, "2": 0, "3": 0}
        priority_weighted_score = 0.0
        for contract, project in self.projects.items():
            actual = completion_by_contract.get(contract)
            result = results_by_contract.get(contract)
            if actual and result:
                expected_overrun = max(0, (actual - project.planned_completion_date).days)
                if result.simulated_completion_date != actual or result.overrun_days != expected_overrun:
                    self.add(
                        "results",
                        f"{contract} RESULTS must report completion {actual.isoformat()} and overrun {expected_overrun} days.",
                        input_values={
                            "contract_number": contract,
                            "expected_completion_date": actual.isoformat(),
                            "reported_completion_date": result.simulated_completion_date.isoformat(),
                            "expected_overrun_days": expected_overrun,
                            "reported_overrun_days": result.overrun_days,
                        },
                    )
                if self.schedule.scenario == Scenario.B and expected_overrun:
                    self.add(
                        "planned_date",
                        f"Scenario B contract {contract} completes {expected_overrun} days after its planned completion date.",
                        input_values={
                            "scenario": "B",
                            "contract_number": contract,
                            "planned_completion_date": project.planned_completion_date.isoformat(),
                            "actual_completion_date": actual.isoformat(),
                            "overrun_days": expected_overrun,
                        },
                    )
                priority_overrun[str(project.contract_priority)] += expected_overrun
            for activity in self.instance.activities:
                if activity.contract_number != contract or activity.activity_id not in completion_by_activity:
                    continue
                activity_overrun = max(0, (completion_by_activity[activity.activity_id] - project.planned_completion_date).days)
                multiplier = {1: 0.3, 2: 0.2, 3: 0.0}[activity.activity_priority]
                base_weight = {1: 100, 2: 10, 3: 1}[project.contract_priority]
                priority_weighted_score += base_weight * (1 + multiplier) * activity_overrun
        excess_total = sum(max(0, count - self.supply[location]) for (location, _), count in possession_count.items() if location in self.supply)
        eclo_total = sum(1 for assignment in self.schedule.access_assignments if assignment.eclo)
        score = (0 if self.schedule.scenario == Scenario.B else priority_weighted_score) + (0 if self.schedule.scenario == Scenario.A else 7 * excess_total + 5 * eclo_total)
        return {
            "scenario": self.schedule.scenario.value,
            "overrun_days_total": sum(priority_overrun.values()),
            "contracts_overrunning": sum(1 for contract, project in self.projects.items() if completion_by_contract.get(contract, project.planned_completion_date) > project.planned_completion_date),
            "excess_access_nights_total": excess_total,
            "eclo_nights_total": eclo_total,
            "priority_overrun": priority_overrun,
            "priority_weighted_score": priority_weighted_score,
            "objective_score": score,
            "formula_version": "local-preflight-1",
        }

    def run(self) -> ValidationReport:
        groups_by_activity_week, accesses_by_activity = self.validate_schedule_shape()
        self.validate_workload_dates_and_precedence(accesses_by_activity)
        possession_count = self.validate_mixes_capacity_and_closures(groups_by_activity_week)
        self.validate_allocation_and_eclo(accesses_by_activity)
        soft_scores = self.validate_results(accesses_by_activity, possession_count)
        report = OfficialValidatorAdapter().local_contract_check()
        report.message = (
            "Local preflight completed: "
            + ("no implemented hard-rule violations found" if not self.violations else f"{len(self.violations)} hard-rule violation(s) found")
            + ". This result is unverified; submit to the organiser validator website for the feasibility decision."
        )
        report.hard_violations = self.violations
        report.soft_scores = soft_scores
        report.detail = {
            "preflight_version": "1",
            "implemented_rules": ["workload", "planned_date", "precedence", "topology", "mix", "weekly_allocation", "workfront", "capacity", "eclo", "results"],
            "derived_closure_rules": ["buffer footprint", "Live opposite-bound mirroring", "Live H01/H02 cross-line footprint"],
            "warnings": self.warnings,
        }
        return report


def preparation_report(findings: tuple[PreparationFinding, ...]) -> ValidationReport:
    """Expose shared preprocessing findings without implying organiser verification."""

    report = OfficialValidatorAdapter().local_contract_check()
    report.message = (
        f"Local preflight could not evaluate a schedule because shared preprocessing found "
        f"{len(findings)} hard input violation(s). This result is unverified."
    )
    report.hard_violations = [
        {
            "rule": finding.rule,
            "severity": "hard",
            "detail": finding.detail,
            "source_file": finding.source_file,
            "row": finding.row,
            "field": finding.field,
            "activity_ids": list(finding.activity_ids),
            "location_ids": list(finding.location_ids),
            "week": finding.week,
        }
        for finding in findings
    ]
    report.detail = {
        "preflight_version": "1",
        "implemented_rules": ["shared_preprocessing"],
        "derived_closure_rules": [],
        "warnings": ["Schedule-derived checks were skipped because the input package is inconsistent."],
    }
    return report


def validate_schedule(prepared: PreparedInstance, schedule: ScenarioSchedule) -> ValidationReport:
    """Validate a schedule against the canonical prepared domain representation."""

    return _Preflight(prepared, schedule).run()


def validate_submission(instance_dir: Path, submission_dir: Path) -> ValidationReport:
    """Convenience entry point for the local preflight command and CI."""

    preparation = prepare_instance(load_instance(instance_dir))
    if preparation.prepared is None:
        return preparation_report(preparation.findings)
    return validate_schedule(preparation.prepared, load_submission(submission_dir))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run For Rails' local, unverified PS1 preflight.")
    parser.add_argument("--instance", type=Path, required=True, help="directory containing the eight official input CSVs")
    parser.add_argument("--submission", type=Path, required=True, help="directory containing the three output CSVs")
    args = parser.parse_args()
    try:
        report = validate_submission(args.instance, args.submission)
    except (OSError, SubmissionLoadError, ValueError) as error:
        print(json.dumps({"status": "unverified", "error": str(error)}, indent=2))
        return 2
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    return 1 if report.hard_violations else 0


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI.
    raise SystemExit(main())
