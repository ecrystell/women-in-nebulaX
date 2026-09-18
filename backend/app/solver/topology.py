"""Validated network and activity-footprint preprocessing for the solver."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from ..domain.models import (
    ActivityRecord,
    Bound,
    InstanceBundle,
    NatureOfWorks,
    ProjectRecord,
)


class SolverInputError(ValueError):
    """The eight CSVs are parseable but inconsistent for scheduling."""


@dataclass(frozen=True)
class Route:
    line_code: str
    bound: Bound
    first_sector_seq: int
    last_sector_seq: int


@dataclass(frozen=True)
class PreparedActivity:
    activity: ActivityRecord
    project: ProjectRecord
    route: Route
    base_locations: frozenset[str]
    closure_locations: frozenset[str]
    planned_start_week: int
    candidate_weeks: tuple[int, ...]


@dataclass(frozen=True)
class PlanningCalendar:
    horizon_start: date
    horizon_weeks: int

    def planned_week(self, value: date) -> int:
        return ((value - self.horizon_start).days // 7) + 1

    def week_end(self, week: int) -> date:
        return self.horizon_start.fromordinal(
            self.horizon_start.toordinal() + week * 7 - 1
        )


@dataclass(frozen=True)
class PreparedInstance:
    instance: InstanceBundle
    calendar: PlanningCalendar
    projects: dict[str, ProjectRecord]
    activities: tuple[PreparedActivity, ...]
    supply: dict[str, int]


def _parameter_map(instance: InstanceBundle) -> dict[str, str]:
    values: dict[str, str] = {}
    for parameter in instance.parameters:
        if parameter.key in values:
            raise SolverInputError(f"06_PARAMETERS.csv contains duplicate key {parameter.key!r}.")
        values[parameter.key] = parameter.value
    return values


class NetworkTopology:
    """Topology index used by both candidate generation and hard constraints."""

    def __init__(self, instance: InstanceBundle) -> None:
        self.instance = instance
        self.sectors_by_line_seq = {
            (sector.line_code, sector.seq): sector for sector in instance.sectors
        }
        self.sectors_by_id = {sector.sector_id: sector for sector in instance.sectors}
        self.stations_by_line_seq = {
            (station.line_code, station.seq): station for station in instance.stations
        }
        self.stations_by_line_id = {
            (station.line_code, station.station_id): station for station in instance.stations
        }
        self.supply = {record.location_id for record in instance.location_supply}
        self.buffer_size = {
            record.nature_of_works: record.up_to_buffer_sectors
            for record in instance.buffer_locations
        }
        self.opposite_bound_required = {
            record.nature_of_works: bool(record.opposite_bound_required)
            for record in instance.buffer_locations
        }

    @staticmethod
    def _location_id(kind: str, line: str, station_or_sector: str, bound: Bound) -> str:
        return f"{kind}:{line}:{station_or_sector}:{bound.value}"

    def route_for(self, activity: ActivityRecord) -> Route:
        try:
            start_sector_id, start_bound_text = activity.start_location_id.rsplit(":", 1)
            end_sector_id, end_bound_text = activity.end_location_id.rsplit(":", 1)
            start_bound = Bound(start_bound_text)
            end_bound = Bound(end_bound_text)
            start_sector = self.sectors_by_id[start_sector_id]
            end_sector = self.sectors_by_id[end_sector_id]
        except (KeyError, ValueError) as error:
            raise SolverInputError(
                f"{activity.activity_id} has an unknown or malformed SEC working section."
            ) from error

        if start_sector.line_code != end_sector.line_code or start_bound != end_bound:
            raise SolverInputError(
                f"{activity.activity_id} must use one line and one bound from start to end."
            )
        return Route(
            line_code=start_sector.line_code,
            bound=start_bound,
            first_sector_seq=min(start_sector.seq, end_sector.seq),
            last_sector_seq=max(start_sector.seq, end_sector.seq),
        )

    def _locations_for_range(
        self, line: str, bound: Bound, first: int, last: int
    ) -> set[str]:
        line_sectors = [
            sector
            for (sector_line, _), sector in self.sectors_by_line_seq.items()
            if sector_line == line
        ]
        if not line_sectors:
            return set()
        minimum = min(sector.seq for sector in line_sectors)
        maximum = max(sector.seq for sector in line_sectors)
        first = max(first, minimum)
        last = min(last, maximum)
        if first > last:
            return set()

        locations = {
            self._location_id(
                "SEC",
                line,
                self.sectors_by_line_seq[(line, sector_seq)].sector_id.rsplit(":", 1)[1],
                bound,
            )
            for sector_seq in range(first, last + 1)
            if (line, sector_seq) in self.sectors_by_line_seq
        }

        first_sector = self.sectors_by_line_seq.get((line, first))
        last_sector = self.sectors_by_line_seq.get((line, last))
        if first_sector and last_sector:
            first_station = self.stations_by_line_id.get(
                (line, first_sector.from_station_id)
            )
            last_station = self.stations_by_line_id.get((line, last_sector.to_station_id))
            if first_station and last_station:
                for station_seq in range(
                    min(first_station.seq, last_station.seq),
                    max(first_station.seq, last_station.seq) + 1,
                ):
                    station = self.stations_by_line_seq.get((line, station_seq))
                    if station:
                        locations.add(
                            self._location_id("PLAT", line, station.station_id, bound)
                        )
        return locations

    def base_locations(self, activity: ActivityRecord) -> frozenset[str]:
        route = self.route_for(activity)
        locations = self._locations_for_range(
            route.line_code, route.bound, route.first_sector_seq, route.last_sector_seq
        )
        return frozenset(locations)

    def closure_locations(self, activity: ActivityRecord) -> frozenset[str]:
        route = self.route_for(activity)
        project_nature = next(
            project.nature_of_activity
            for project in self.instance.projects
            if project.contract_number == activity.contract_number
        )
        extension = self.buffer_size.get(project_nature, 0)
        locations = self._locations_for_range(
            route.line_code,
            route.bound,
            route.first_sector_seq - extension,
            route.last_sector_seq + extension,
        )

        if self.opposite_bound_required.get(project_nature, False):
            opposite = Bound.WESTBOUND if route.bound is Bound.EASTBOUND else Bound.EASTBOUND
            locations |= self._locations_for_range(
                route.line_code,
                opposite,
                route.first_sector_seq - extension,
                route.last_sector_seq + extension,
            )
            # The PS1 interchange exception is limited to Live work and only
            # H01/H02 platforms plus the H01_H02 tunnel on the other line.
            # Other work natures do not cross from Alpha to Beta (or vice versa).
        if project_nature is NatureOfWorks.LIVE:
            for location in tuple(locations):
                kind, line, part, bound = location.split(":")
                if part not in {"H01", "H02", "H01_H02"}:
                    continue
                other_line = {"ALP": "BET", "BET": "ALP"}.get(line)
                if other_line:
                    other = f"{kind}:{other_line}:{part}:{bound}"
                    if other in self.supply:
                        locations.add(other)
        return frozenset(locations)


def _detect_predecessor_cycles(activities: dict[str, ActivityRecord]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(activity_id: str) -> None:
        if activity_id in visiting:
            raise SolverInputError(f"predecessor cycle detected at activity {activity_id}.")
        if activity_id in visited:
            return
        visiting.add(activity_id)
        predecessor = activities[activity_id].predecessor_activity_id
        if predecessor:
            visit(predecessor)
        visiting.remove(activity_id)
        visited.add(activity_id)

    for activity_id in activities:
        visit(activity_id)


def prepare_instance(instance: InstanceBundle) -> PreparedInstance:
    """Validate cross-file references and derive reusable activity footprints."""

    parameters = _parameter_map(instance)
    try:
        horizon_start = date.fromisoformat(parameters["horizon_start"])
        horizon_weeks = int(parameters["horizon_weeks"])
    except (KeyError, ValueError) as error:
        raise SolverInputError(
            "06_PARAMETERS.csv must define a valid horizon_start and positive horizon_weeks."
        ) from error
    if horizon_weeks <= 0:
        raise SolverInputError("06_PARAMETERS.csv horizon_weeks must be positive.")

    projects: dict[str, ProjectRecord] = {}
    for project in instance.projects:
        if project.contract_number in projects:
            raise SolverInputError(
                f"07_PROJECT_DETAILS.csv contains duplicate contract {project.contract_number}."
            )
        projects[project.contract_number] = project

    activities_by_id: dict[str, ActivityRecord] = {}
    for activity in instance.activities:
        if activity.activity_id in activities_by_id:
            raise SolverInputError(
                f"08_ACTIVITY_DETAILS.csv contains duplicate activity {activity.activity_id}."
            )
        activities_by_id[activity.activity_id] = activity
        project = projects.get(activity.contract_number)
        if project is None:
            raise SolverInputError(
                f"{activity.activity_id} references unknown contract {activity.contract_number}."
            )
        if activity.activity_type != project.activity_type:
            raise SolverInputError(
                f"{activity.activity_id} activity_type does not match contract {activity.contract_number}."
            )
        if activity.predecessor_activity_id and activity.predecessor_activity_id not in activities_by_id:
            # The second pass below handles forward references; this catches no
            # error prematurely, while keeping the eventual message precise.
            continue

    for activity in instance.activities:
        predecessor = activity.predecessor_activity_id
        if predecessor and predecessor not in activities_by_id:
            raise SolverInputError(
                f"{activity.activity_id} references unknown predecessor {predecessor}."
            )
    _detect_predecessor_cycles(activities_by_id)

    topology = NetworkTopology(instance)
    calendar = PlanningCalendar(horizon_start, horizon_weeks)
    supply = {
        record.location_id: record.supply_capacity for record in instance.location_supply
    }
    if len(supply) != len(instance.location_supply):
        raise SolverInputError("04_LOCATION_SUPPLY.csv contains duplicate location IDs.")
    if set(topology.buffer_size) != {
        NatureOfWorks.LIVE,
        NatureOfWorks.NON_LIVE_CONSIST,
        NatureOfWorks.NON_LIVE_OTHERS,
    }:
        raise SolverInputError("05_BUFFER_LOCATION.csv must define all three work natures.")

    prepared: list[PreparedActivity] = []
    for activity in sorted(instance.activities, key=lambda item: item.activity_id):
        project = projects[activity.contract_number]
        route = topology.route_for(activity)
        base = topology.base_locations(activity)
        closure = topology.closure_locations(activity)
        missing = sorted(base - set(supply))
        if missing:
            raise SolverInputError(
                f"{activity.activity_id} footprint references locations absent from supply: {missing}."
            )
        missing_closure = sorted(closure - set(supply))
        if missing_closure:
            raise SolverInputError(
                f"{activity.activity_id} closure footprint references locations absent from supply: {missing_closure}."
            )
        planned_week = calendar.planned_week(activity.planned_start_date)
        if planned_week < 1 or planned_week > horizon_weeks:
            raise SolverInputError(
                f"{activity.activity_id} planned_start_date {activity.planned_start_date} is outside the planning horizon."
            )
        candidate_weeks = tuple(range(planned_week, horizon_weeks + 1))
        if activity.total_accesses > len(candidate_weeks):
            raise SolverInputError(
                f"{activity.activity_id} needs {activity.total_accesses} accesses but only "
                f"{len(candidate_weeks)} weeks remain after its planned start."
            )
        prepared.append(
            PreparedActivity(
                activity=activity,
                project=project,
                route=route,
                base_locations=base,
                closure_locations=closure,
                planned_start_week=planned_week,
                candidate_weeks=candidate_weeks,
            )
        )

    return PreparedInstance(
        instance=instance,
        calendar=calendar,
        projects=projects,
        activities=tuple(prepared),
        supply=supply,
    )
