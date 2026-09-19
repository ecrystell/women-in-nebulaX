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
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, ValidationError

from app.domain.models import (
    AccessAssignment,
    ActivityRecord,
    Bound,
    ContractResult,
    InstanceBundle,
    NatureOfWorks,
    OccupancyAssignment,
    Scenario,
    ScenarioSchedule,
)
from app.exports.csv_writer import ACCESS_HEADERS, OCCUPANCY_HEADERS, RESULT_HEADERS
from app.ingestion.csv_loader import load_instance
from app.domain.preprocessing import PreparedInstance, PreparationFinding
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


@dataclass(frozen=True)
class _Route:
    line_code: str
    bound: Bound
    first_sector_seq: int
    last_sector_seq: int


class _Preflight:
    def __init__(
        self,
        instance: InstanceBundle,
        schedule: ScenarioSchedule,
        supply_overrides: dict[tuple[str, int], int] | None = None,
    ) -> None:
        self.instance = instance
        self.schedule = schedule
        self.violations: list[dict[str, object]] = []
        self.projects = {project.contract_number: project for project in instance.projects}
        self.activities = {activity.activity_id: activity for activity in instance.activities}
        self.supply = {record.location_id: record for record in instance.location_supply}
        self.supply_overrides = supply_overrides or {}
        self.sectors_by_line_seq = {
            (sector.line_code, sector.seq): sector for sector in instance.sectors
        }
        self.stations_by_line_seq = {
            (station.line_code, station.seq): station for station in instance.stations
        }
        self.stations_by_line_id = {
            (station.line_code, station.station_id): station for station in instance.stations
        }
        self.sector_seq_by_id = {sector.sector_id: sector.seq for sector in instance.sectors}
        self.buffer_size = {
            record.nature_of_works: record.up_to_buffer_sectors
            for record in instance.buffer_locations
        }
        self.horizon_start = self._parameter_date("horizon_start")
        self.horizon_weeks = self._parameter_int("horizon_weeks")
        self.warnings: list[str] = []

    def supply_capacity(self, location_id: str, week: int) -> int:
        record = self.supply.get(location_id)
        return self.supply_overrides.get(
            (location_id, week), record.supply_capacity if record else 0
        )

    def _parameter_date(self, key: str) -> date | None:
        value = next((parameter.value for parameter in self.instance.parameters if parameter.key == key), None)
        try:
            return date.fromisoformat(value) if value else None
        except ValueError:
            self.add("input", f"Parameter {key!r} is not an ISO date.")
            return None

    def _parameter_int(self, key: str) -> int | None:
        value = next((parameter.value for parameter in self.instance.parameters if parameter.key == key), None)
        try:
            parsed = int(value) if value else None
            if parsed is None or parsed <= 0:
                raise ValueError
            return parsed
        except ValueError:
            self.add("input", f"Parameter {key!r} is not a positive integer.")
            return None

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

    def route_for(self, activity: ActivityRecord) -> _Route | None:
        try:
            start_sector_id, start_bound = activity.start_location_id.rsplit(":", 1)
            end_sector_id, end_bound = activity.end_location_id.rsplit(":", 1)
            start_seq = self.sector_seq_by_id[start_sector_id]
            end_seq = self.sector_seq_by_id[end_sector_id]
            start_sector = self.sectors_by_line_seq[(start_sector_id.split(":")[1], start_seq)]
            end_sector = self.sectors_by_line_seq[(end_sector_id.split(":")[1], end_seq)]
            bound = Bound(start_bound)
        except (KeyError, ValueError, IndexError):
            self.add("input", f"{activity.activity_id} has an unknown or malformed working section.", activity_ids=[activity.activity_id])
            return None
        if start_sector.line_code != end_sector.line_code or start_bound != end_bound:
            self.add("input", f"{activity.activity_id} must use one line and bound.", activity_ids=[activity.activity_id])
            return None
        return _Route(start_sector.line_code, bound, min(start_seq, end_seq), max(start_seq, end_seq))

    @staticmethod
    def _location_id(kind: str, line: str, station_or_sector: str, bound: Bound) -> str:
        return f"{kind}:{line}:{station_or_sector}:{bound.value}"

    def _locations_for_range(self, line: str, bound: Bound, first: int, last: int) -> set[str]:
        locations: set[str] = set()
        line_sectors = [sector for (sector_line, _), sector in self.sectors_by_line_seq.items() if sector_line == line]
        if not line_sectors:
            return locations
        min_seq, max_seq = min(sector.seq for sector in line_sectors), max(sector.seq for sector in line_sectors)
        first, last = max(first, min_seq), min(last, max_seq)
        for sector_seq in range(first, last + 1):
            sector = self.sectors_by_line_seq.get((line, sector_seq))
            if sector:
                locations.add(self._location_id("SEC", line, sector.sector_id.rsplit(":", 1)[1], bound))
        # A sector range from i..j occupies every station from sector i's book-in
        # through sector j's book-out, including both platform endpoints.
        first_sector = self.sectors_by_line_seq.get((line, first))
        last_sector = self.sectors_by_line_seq.get((line, last))
        if first_sector and last_sector:
            first_station = self.stations_by_line_id.get((line, first_sector.from_station_id))
            last_station = self.stations_by_line_id.get((line, last_sector.to_station_id))
            if first_station and last_station:
                for station_seq in range(min(first_station.seq, last_station.seq), max(first_station.seq, last_station.seq) + 1):
                    station = self.stations_by_line_seq.get((line, station_seq))
                    if station:
                        locations.add(self._location_id("PLAT", line, station.station_id, bound))
        return locations

    def base_locations(self, activity: ActivityRecord) -> set[str]:
        route = self.route_for(activity)
        return self._locations_for_range(route.line_code, route.bound, route.first_sector_seq, route.last_sector_seq) if route else set()

    def closure_locations(self, activity: ActivityRecord) -> set[str]:
        route = self.route_for(activity)
        if route is None:
            return set()
        extension = self.buffer_size.get(activity_nature := self.projects.get(activity.contract_number).nature_of_activity if self.projects.get(activity.contract_number) else None, 0)
        locations = self._locations_for_range(
            route.line_code, route.bound, route.first_sector_seq - extension, route.last_sector_seq + extension
        )
        if activity_nature == NatureOfWorks.LIVE:
            mirrored_bound = Bound.WESTBOUND if route.bound == Bound.EASTBOUND else Bound.EASTBOUND
            locations |= self._locations_for_range(
                route.line_code, mirrored_bound, route.first_sector_seq - extension, route.last_sector_seq + extension
            )
            # The interchange exception is line-crossing only for Live work.  It
            # applies to H01/H02 platforms and the H01_H02 tunnel, on both bounds
            # because Live work has already mirrored onto the opposite bound.
            for location in list(locations):
                kind, line, part, bound = location.split(":")
                if part in {"H01", "H02", "H01_H02"}:
                    other_line = "BET" if line == "ALP" else "ALP" if line == "BET" else None
                    if other_line:
                        other = f"{kind}:{other_line}:{part}:{bound}"
                        if other in self.supply:
                            locations.add(other)
            # Organiser traces show that a Live H01-H02 power isolation carries
            # its published buffer onto the other line as well as closing that
            # line's hub tunnel/platforms.  Expand from the other line's hub
            # sector on both bounds so those cross-line buffer locations are
            # evidence-bearing rather than implicit.
            base_parts = {location.split(":")[2] for location in self.base_locations(activity)}
            if "H01_H02" in base_parts:
                other_line = "BET" if route.line_code == "ALP" else "ALP" if route.line_code == "BET" else None
                if other_line:
                    hub_sector = next(
                        (
                            sector
                            for (line, _), sector in self.sectors_by_line_seq.items()
                            if line == other_line and sector.sector_id.endswith(":H01_H02")
                        ),
                        None,
                    )
                    if hub_sector:
                        for bound in Bound:
                            locations |= self._locations_for_range(
                                other_line,
                                bound,
                                hub_sector.seq - extension,
                                hub_sector.seq + extension,
                            )
        return locations

    def week_end(self, week: int) -> date | None:
        return self.horizon_start + timedelta(days=week * 7 - 1) if self.horizon_start else None

    def planned_week(self, value: date) -> int | None:
        return ((value - self.horizon_start).days // 7) + 1 if self.horizon_start else None

    def validate_input_references(self) -> None:
        line_codes = [line.line_code for line in self.instance.lines]
        if len(line_codes) != len(set(line_codes)):
            self.add("input", "LINES contains duplicate line_code values.")
        station_keys = [(station.line_code, station.station_id) for station in self.instance.stations]
        station_sequences = [(station.line_code, station.seq) for station in self.instance.stations]
        if len(station_keys) != len(set(station_keys)):
            self.add("input", "STATIONS contains duplicate (line_code, station_id) values.")
        if len(station_sequences) != len(set(station_sequences)):
            self.add("input", "STATIONS contains duplicate (line_code, seq) values.")
        sector_ids = [sector.sector_id for sector in self.instance.sectors]
        sector_sequences = [(sector.line_code, sector.seq) for sector in self.instance.sectors]
        if len(sector_ids) != len(set(sector_ids)):
            self.add("input", "SECTORS contains duplicate sector_id values.")
        if len(sector_sequences) != len(set(sector_sequences)):
            self.add("input", "SECTORS contains duplicate (line_code, seq) values.")
        known_lines = set(line_codes)
        known_stations = set(station_keys)
        for station in self.instance.stations:
            if station.line_code not in known_lines:
                self.add("input", f"Station {station.station_id} references unknown line {station.line_code}.")
        for sector in self.instance.sectors:
            if sector.line_code not in known_lines:
                self.add("input", f"Sector {sector.sector_id} references unknown line {sector.line_code}.")
            for station_id in (sector.from_station_id, sector.to_station_id):
                if (sector.line_code, station_id) not in known_stations:
                    self.add("input", f"Sector {sector.sector_id} references unknown station {station_id}.")
        supply_ids = [record.location_id for record in self.instance.location_supply]
        if len(supply_ids) != len(set(supply_ids)):
            self.add("input", "LOCATION_SUPPLY contains duplicate location_id values.")
        for record in self.instance.location_supply:
            parts = record.location_id.split(":")
            if len(parts) != 4 or parts[1] != record.line_code or parts[3] != record.bound.value:
                self.add("input", f"LOCATION_SUPPLY metadata does not match {record.location_id}.", location_ids=[record.location_id])
        parameter_keys = [record.key for record in self.instance.parameters]
        if len(parameter_keys) != len(set(parameter_keys)):
            self.add("input", "PARAMETERS contains duplicate keys.")
        buffer_natures = [record.nature_of_works for record in self.instance.buffer_locations]
        if len(buffer_natures) != len(set(buffer_natures)):
            self.add("input", "BUFFER_LOCATION contains duplicate nature_of_works rows.")
        missing_natures = set(NatureOfWorks) - set(buffer_natures)
        if missing_natures:
            self.add("input", f"BUFFER_LOCATION is missing {sorted(item.value for item in missing_natures)}.")
        if len(self.projects) != len(self.instance.projects):
            self.add("input", "PROJECT_DETAILS contains duplicate contract_number values.")
        if len(self.activities) != len(self.instance.activities):
            self.add("input", "ACTIVITY_DETAILS contains duplicate activity_id values.")
        for activity in self.instance.activities:
            project = self.projects.get(activity.contract_number)
            if project is None:
                self.add("input", f"{activity.activity_id} references unknown contract {activity.contract_number}.", activity_ids=[activity.activity_id])
                continue
            if activity.activity_type != project.activity_type:
                self.add("input", f"{activity.activity_id} activity_type does not match its contract.", activity_ids=[activity.activity_id])
            self.route_for(activity)
            if activity.predecessor_activity_id and activity.predecessor_activity_id not in self.activities:
                self.add("precedence", f"{activity.activity_id} references unknown predecessor {activity.predecessor_activity_id}.", activity_ids=[activity.activity_id])
        # Detect predecessor cycles before schedule evaluation, including longer cycles.
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(activity_id: str) -> None:
            if activity_id in visiting:
                self.add("precedence", f"Predecessor cycle includes {activity_id}.", activity_ids=[activity_id])
                return
            if activity_id in visited:
                return
            visiting.add(activity_id)
            predecessor = self.activities[activity_id].predecessor_activity_id
            if predecessor in self.activities:
                visit(predecessor)
            visiting.remove(activity_id)
            visited.add(activity_id)

        for activity_id in self.activities:
            visit(activity_id)

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
                self.add("workload", f"{activity.activity_id} delivers {yield_total:g} of required {activity.total_accesses:g} access units.", activity_ids=[activity.activity_id])
            if not assignments:
                continue
            first_week[activity.activity_id] = min(item.week for item in assignments)
            last_week[activity.activity_id] = max(item.week for item in assignments)
            planned_week = self.planned_week(activity.planned_start_date)
            if planned_week and first_week[activity.activity_id] < planned_week:
                self.add("planned_date", f"{activity.activity_id} starts in week {first_week[activity.activity_id]} before planned week {planned_week}.", activity_ids=[activity.activity_id], week=first_week[activity.activity_id])
        for activity in self.instance.activities:
            predecessor = activity.predecessor_activity_id
            if predecessor and predecessor in last_week and activity.activity_id in first_week and first_week[activity.activity_id] <= last_week[predecessor]:
                self.add("precedence", f"{activity.activity_id} starts in week {first_week[activity.activity_id]} before predecessor {predecessor} finishes in week {last_week[predecessor]}.", activity_ids=[predecessor, activity.activity_id], week=first_week[activity.activity_id])

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
                self.add("mix", f"Illegal possession mix at {location_id}, week {week}, group {group}: {types}.", activity_ids=members, location_ids=[location_id], week=week)

        for (location_id, week), count in possession_count.items():
            capacity = self.supply_capacity(location_id, week)
            allowed = capacity if self.schedule.scenario in {Scenario.A, Scenario.B} else capacity + 1
            if self.schedule.scenario == Scenario.A and count > allowed:
                self.add("capacity", f"{location_id} has {count} possessions in week {week}; Scenario A capacity is {capacity}.", location_ids=[location_id], week=week)
            elif self.schedule.scenario == Scenario.C and count > allowed:
                self.add("capacity", f"{location_id} has {count} possessions in week {week}; Scenario C limit is supply {capacity} + 1.", location_ids=[location_id], week=week)

        if groups_by_activity_week:
            self.warnings.append(
                "Closure footprints are derived, but the three output CSVs do not expose a global ordering "
                "for different possession groups. Cross-group closure conflicts therefore remain an "
                "organiser-validator-only decision; local preflight does not infer concurrency."
            )
        return possession_count

    def validate_allocation_and_eclo(self, accesses_by_activity: dict[str, list[AccessAssignment]]) -> None:
        by_contract_type_week: dict[tuple[str, str, int], list[AccessAssignment]] = defaultdict(list)
        eclo_weeks_by_line: dict[str, set[int]] = defaultdict(set)
        for activity_id, assignments in accesses_by_activity.items():
            activity = self.activities.get(activity_id)
            if not activity or activity.contract_number not in self.projects:
                continue
            project = self.projects[activity.contract_number]
            for assignment in assignments:
                by_contract_type_week[(activity.contract_number, activity.activity_type, assignment.week)].append(assignment)
                if self.schedule.scenario == Scenario.A and assignment.eclo:
                    self.add("eclo", f"Scenario A forbids ECLO ({activity_id}, week {assignment.week}).", activity_ids=[activity_id], week=assignment.week)
                if self.schedule.scenario == Scenario.C and assignment.eclo:
                    lines = {location.split(":")[1] for location in self.closure_locations(activity)}
                    for line in lines:
                        eclo_weeks_by_line[line].add(assignment.week)
        for (contract, activity_type, week), assignments in by_contract_type_week.items():
            project = self.projects[contract]
            nights = {assignment.access_night for assignment in assignments}
            if len(nights) > project.number_of_maximum_access_per_week:
                self.add("weekly_allocation", f"{contract}/{activity_type} uses {len(nights)} access nights in week {week}; cap is {project.number_of_maximum_access_per_week}.", activity_ids=[assignment.activity_id for assignment in assignments], week=week)
            for night in nights:
                activity_ids = {assignment.activity_id for assignment in assignments if assignment.access_night == night}
                if len(activity_ids) > project.number_of_workfronts:
                    self.add("workfront", f"{contract}/{activity_type} runs {len(activity_ids)} activities on access night {night} in week {week}; workfront cap is {project.number_of_workfronts}.", activity_ids=activity_ids, week=week)
        for line, weeks in eclo_weeks_by_line.items():
            if weeks and max(weeks) - min(weeks) + 1 > 2:
                self.add("eclo", f"Scenario C ECLO on line {line} spans weeks {min(weeks)} to {max(weeks)}; maximum continuous window is two weeks.", week=min(weeks))

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
            contract_overrun = (
                max(0, (actual - project.planned_completion_date).days)
                if actual
                else 0
            )
            if actual and result:
                if result.simulated_completion_date != actual or result.overrun_days != contract_overrun:
                    self.add("results", f"{contract} RESULTS must report completion {actual.isoformat()} and overrun {contract_overrun} days.")
                if self.schedule.scenario == Scenario.B and contract_overrun:
                    self.add("planned_date", f"Scenario B contract {contract} completes {contract_overrun} days after its planned completion date.")
                priority_overrun[str(project.contract_priority)] += contract_overrun
            for activity in self.instance.activities:
                if activity.contract_number != contract:
                    continue
                multiplier = {1: 0.3, 2: 0.2, 3: 0.0}[activity.activity_priority]
                base_weight = {1: 100, 2: 10, 3: 1}[project.contract_priority]
                # The organiser applies the contract's final overrun to every
                # activity-priority nudge in that contract. Scoring each
                # activity's own finish date understates the published score.
                priority_weighted_score += base_weight * (1 + multiplier) * contract_overrun
        excess_total = sum(
            max(0, count - self.supply_capacity(location, week))
            for (location, week), count in possession_count.items()
            if location in self.supply
        )
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
        self.validate_input_references()
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
        "Local preflight could not evaluate a schedule because shared preprocessing found "
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


def validate_schedule(
    instance: InstanceBundle | PreparedInstance,
    schedule: ScenarioSchedule,
    supply_overrides: dict[tuple[str, int], int] | None = None,
) -> ValidationReport:
    """Validate a typed schedule against a typed input bundle locally."""

    if isinstance(instance, PreparedInstance):
        instance = instance.instance
    return _Preflight(instance, schedule, supply_overrides).run()


def validate_submission(instance_dir: Path, submission_dir: Path) -> ValidationReport:
    """Convenience entry point for the local preflight command and CI."""

    return validate_schedule(load_instance(instance_dir), load_submission(submission_dir))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RailAccess AI's local, unverified PS1 preflight.")
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
