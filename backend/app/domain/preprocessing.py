"""Canonical cross-file preparation for scheduling and local validation.

This is deliberately domain-owned: a solver and a validator must consult the
same route, footprint, calendar, and predecessor interpretation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .models import ActivityRecord, Bound, InstanceBundle, NatureOfWorks, ProjectRecord


@dataclass(frozen=True)
class PreparationFinding:
    """One actionable, non-schema problem in an otherwise parseable instance."""

    rule: str
    detail: str
    source_file: str | None = None
    row: int | None = None
    field: str | None = None
    activity_ids: tuple[str, ...] = ()
    location_ids: tuple[str, ...] = ()
    week: int | None = None


class PreparationError(ValueError):
    """Raised when a caller requires a complete prepared instance."""

    def __init__(self, findings: tuple[PreparationFinding, ...]) -> None:
        self.findings = findings
        summary = "; ".join(finding.detail for finding in findings)
        super().__init__(summary or "Instance preprocessing failed.")


@dataclass(frozen=True)
class PreparationResult:
    prepared: PreparedInstance | None
    findings: tuple[PreparationFinding, ...]

    @property
    def is_valid(self) -> bool:
        return self.prepared is not None and not self.findings


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
        return self.horizon_start.fromordinal(self.horizon_start.toordinal() + week * 7 - 1)


@dataclass(frozen=True)
class PreparedInstance:
    instance: InstanceBundle
    calendar: PlanningCalendar
    projects: dict[str, ProjectRecord]
    activities: tuple[PreparedActivity, ...]
    supply: dict[str, int]

    @property
    def activities_by_id(self) -> dict[str, PreparedActivity]:
        return {item.activity.activity_id: item for item in self.activities}


_TABLES = {
    "parameters": "06_PARAMETERS.csv",
    "projects": "07_PROJECT_DETAILS.csv",
    "activities": "08_ACTIVITY_DETAILS.csv",
    "location_supply": "04_LOCATION_SUPPLY.csv",
    "buffer_locations": "05_BUFFER_LOCATION.csv",
}


class _Findings:
    def __init__(self, instance: InstanceBundle) -> None:
        self.instance = instance
        self.items: list[PreparationFinding] = []

    def row_for(self, table: str, record: object) -> int | None:
        for index, item in enumerate(getattr(self.instance, table), start=2):
            if item is record:
                return index
        return None

    def add(
        self,
        detail: str,
        *,
        rule: str = "input",
        table: str | None = None,
        record: object | None = None,
        field: str | None = None,
        activity_ids: tuple[str, ...] = (),
        location_ids: tuple[str, ...] = (),
    ) -> None:
        self.items.append(
            PreparationFinding(
                rule=rule,
                detail=detail,
                source_file=_TABLES.get(table) if table else None,
                row=self.row_for(table, record) if table and record is not None else None,
                field=field,
                activity_ids=activity_ids,
                location_ids=location_ids,
            )
        )


class NetworkTopology:
    """Canonical route and footprint expansion for a valid input package."""

    def __init__(
        self,
        instance: InstanceBundle,
        projects: dict[str, ProjectRecord],
        supply_ids: set[str],
    ) -> None:
        self.instance = instance
        self.projects = projects
        self.supply_ids = supply_ids
        self.sectors_by_line_seq = {(sector.line_code, sector.seq): sector for sector in instance.sectors}
        self.sectors_by_id = {sector.sector_id: sector for sector in instance.sectors}
        self.stations_by_line_seq = {(station.line_code, station.seq): station for station in instance.stations}
        self.stations_by_line_id = {(station.line_code, station.station_id): station for station in instance.stations}
        self.buffer_size = {record.nature_of_works: record.up_to_buffer_sectors for record in instance.buffer_locations}
        self.opposite_bound_required = {
            record.nature_of_works: bool(record.opposite_bound_required)
            for record in instance.buffer_locations
        }

    @staticmethod
    def _location_id(kind: str, line: str, station_or_sector: str, bound: Bound) -> str:
        return f"{kind}:{line}:{station_or_sector}:{bound.value}"

    def route_for(self, activity: ActivityRecord) -> Route:
        start_sector_id, start_bound_text = activity.start_location_id.rsplit(":", 1)
        end_sector_id, end_bound_text = activity.end_location_id.rsplit(":", 1)
        start_bound = Bound(start_bound_text)
        end_bound = Bound(end_bound_text)
        start_sector = self.sectors_by_id[start_sector_id]
        end_sector = self.sectors_by_id[end_sector_id]
        if start_sector.line_code != end_sector.line_code or start_bound != end_bound:
            raise ValueError("working section must use one line and one bound from start to end")
        return Route(
            line_code=start_sector.line_code,
            bound=start_bound,
            first_sector_seq=min(start_sector.seq, end_sector.seq),
            last_sector_seq=max(start_sector.seq, end_sector.seq),
        )

    def _locations_for_range(self, line: str, bound: Bound, first: int, last: int) -> set[str]:
        line_sectors = [sector for (sector_line, _), sector in self.sectors_by_line_seq.items() if sector_line == line]
        if not line_sectors:
            return set()
        first = max(first, min(sector.seq for sector in line_sectors))
        last = min(last, max(sector.seq for sector in line_sectors))
        if first > last:
            return set()
        locations = {
            self._location_id("SEC", line, self.sectors_by_line_seq[(line, sequence)].sector_id.rsplit(":", 1)[1], bound)
            for sequence in range(first, last + 1)
            if (line, sequence) in self.sectors_by_line_seq
        }
        first_sector = self.sectors_by_line_seq.get((line, first))
        last_sector = self.sectors_by_line_seq.get((line, last))
        if first_sector and last_sector:
            first_station = self.stations_by_line_id.get((line, first_sector.from_station_id))
            last_station = self.stations_by_line_id.get((line, last_sector.to_station_id))
            if first_station and last_station:
                for sequence in range(min(first_station.seq, last_station.seq), max(first_station.seq, last_station.seq) + 1):
                    station = self.stations_by_line_seq.get((line, sequence))
                    if station:
                        locations.add(self._location_id("PLAT", line, station.station_id, bound))
        return locations

    def base_locations(self, route: Route) -> frozenset[str]:
        return frozenset(self._locations_for_range(route.line_code, route.bound, route.first_sector_seq, route.last_sector_seq))

    def closure_locations(self, route: Route, project: ProjectRecord) -> frozenset[str]:
        extension = self.buffer_size[project.nature_of_activity]
        base = set(self.base_locations(route))
        extended = self._locations_for_range(
            route.line_code,
            route.bound,
            route.first_sector_seq - extension,
            route.last_sector_seq + extension,
        )
        if project.nature_of_activity is NatureOfWorks.LIVE:
            # Live power-isolation closes every tunnel and platform reached
            # by the configured buffer-sector range.
            locations = set(extended)
        else:
            # The organiser evidence only extends Consist through tunnel
            # sectors. Booked platforms remain in the base closure.
            locations = base
            locations.update(
                location for location in extended if location.startswith("SEC:")
            )
        if self.opposite_bound_required[project.nature_of_activity]:
            opposite = Bound.WESTBOUND if route.bound is Bound.EASTBOUND else Bound.EASTBOUND
            opposite_extended = self._locations_for_range(
                route.line_code,
                opposite,
                route.first_sector_seq - extension,
                route.last_sector_seq + extension,
            )
            if project.nature_of_activity is NatureOfWorks.LIVE:
                locations.update(opposite_extended)
            else:
                opposite_base = self._locations_for_range(
                    route.line_code,
                    opposite,
                    route.first_sector_seq,
                    route.last_sector_seq,
                )
                locations.update(opposite_base)
                locations.update(
                    location
                    for location in opposite_extended
                    if location.startswith("SEC:")
                )
        if project.nature_of_activity is NatureOfWorks.LIVE:
            affects_interchange = any(
                location.split(":")[2] == "H01_H02" for location in locations
            )
            if affects_interchange:
                other_line = {"ALP": "BET", "BET": "ALP"}.get(route.line_code)
                other_hub_sector = next(
                    (
                        sector
                        for (line, _sequence), sector in self.sectors_by_line_seq.items()
                        if line == other_line and sector.sector_id.rsplit(":", 1)[1] == "H01_H02"
                    ),
                    None,
                )
                if other_line and other_hub_sector:
                    affected_bounds = (Bound.EASTBOUND, Bound.WESTBOUND)
                    for bound in affected_bounds:
                        locations.update(
                            self._locations_for_range(
                                other_line,
                                bound,
                                other_hub_sector.seq - extension,
                                other_hub_sector.seq + extension,
                            )
                        )
        return frozenset(locations)


def _detect_predecessor_cycles(activities: dict[str, ActivityRecord], findings: _Findings) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(activity_id: str) -> None:
        if activity_id in visiting:
            activity = activities[activity_id]
            findings.add(
                f"Predecessor cycle includes {activity_id}.",
                rule="precedence",
                table="activities",
                record=activity,
                field="predecessor_activity_id",
                activity_ids=(activity_id,),
            )
            return
        if activity_id in visited:
            return
        visiting.add(activity_id)
        predecessor = activities[activity_id].predecessor_activity_id
        if predecessor in activities:
            visit(predecessor)
        visiting.remove(activity_id)
        visited.add(activity_id)

    for activity_id in activities:
        visit(activity_id)


def prepare_instance(instance: InstanceBundle) -> PreparationResult:
    """Collect all cross-file findings and build a complete reusable representation."""

    findings = _Findings(instance)
    parameters: dict[str, object] = {}
    for parameter in instance.parameters:
        if parameter.key in parameters:
            findings.add(
                f"06_PARAMETERS.csv contains duplicate key {parameter.key!r}.",
                table="parameters",
                record=parameter,
                field="key",
            )
        else:
            parameters[parameter.key] = parameter

    horizon_start: date | None = None
    horizon_weeks: int | None = None
    start_parameter = parameters.get("horizon_start")
    if start_parameter is None:
        findings.add("06_PARAMETERS.csv must define horizon_start.", table="parameters", field="key")
    else:
        try:
            horizon_start = date.fromisoformat(start_parameter.value)  # type: ignore[attr-defined]
        except ValueError:
            findings.add("horizon_start must be an ISO date.", table="parameters", record=start_parameter, field="value")
    weeks_parameter = parameters.get("horizon_weeks")
    if weeks_parameter is None:
        findings.add("06_PARAMETERS.csv must define horizon_weeks.", table="parameters", field="key")
    else:
        try:
            horizon_weeks = int(weeks_parameter.value)  # type: ignore[attr-defined]
            if horizon_weeks <= 0:
                raise ValueError
        except ValueError:
            findings.add("horizon_weeks must be a positive integer.", table="parameters", record=weeks_parameter, field="value")
            horizon_weeks = None

    projects: dict[str, ProjectRecord] = {}
    for project in instance.projects:
        if project.contract_number in projects:
            findings.add(
                f"07_PROJECT_DETAILS.csv contains duplicate contract {project.contract_number}.",
                table="projects",
                record=project,
                field="contract_number",
            )
        else:
            projects[project.contract_number] = project

    activities: dict[str, ActivityRecord] = {}
    for activity in instance.activities:
        if activity.activity_id in activities:
            findings.add(
                f"08_ACTIVITY_DETAILS.csv contains duplicate activity {activity.activity_id}.",
                table="activities",
                record=activity,
                field="activity_id",
                activity_ids=(activity.activity_id,),
            )
        else:
            activities[activity.activity_id] = activity

    supply: dict[str, int] = {}
    for record in instance.location_supply:
        if record.location_id in supply:
            findings.add(
                f"04_LOCATION_SUPPLY.csv contains duplicate location ID {record.location_id}.",
                table="location_supply",
                record=record,
                field="location_id",
                location_ids=(record.location_id,),
            )
        else:
            supply[record.location_id] = record.supply_capacity

    seen_buffers: set[NatureOfWorks] = set()
    for record in instance.buffer_locations:
        if record.nature_of_works in seen_buffers:
            findings.add(
                f"05_BUFFER_LOCATION.csv contains duplicate nature {record.nature_of_works.value}.",
                table="buffer_locations",
                record=record,
                field="nature_of_works",
            )
        seen_buffers.add(record.nature_of_works)
    expected_natures = {NatureOfWorks.LIVE, NatureOfWorks.NON_LIVE_CONSIST, NatureOfWorks.NON_LIVE_OTHERS}
    if seen_buffers != expected_natures:
        findings.add("05_BUFFER_LOCATION.csv must define all three work natures.", table="buffer_locations", field="nature_of_works")

    for activity in instance.activities:
        project = projects.get(activity.contract_number)
        if project is None:
            findings.add(
                f"{activity.activity_id} references unknown contract {activity.contract_number}.",
                table="activities",
                record=activity,
                field="contract_number",
                activity_ids=(activity.activity_id,),
            )
        elif activity.activity_type != project.activity_type:
            findings.add(
                f"{activity.activity_id} activity_type does not match contract {activity.contract_number}.",
                table="activities",
                record=activity,
                field="activity_type",
                activity_ids=(activity.activity_id,),
            )
        if activity.predecessor_activity_id and activity.predecessor_activity_id not in activities:
            findings.add(
                f"{activity.activity_id} references unknown predecessor {activity.predecessor_activity_id}.",
                rule="precedence",
                table="activities",
                record=activity,
                field="predecessor_activity_id",
                activity_ids=(activity.activity_id,),
            )
    _detect_predecessor_cycles(activities, findings)

    topology = NetworkTopology(instance, projects, set(supply))
    calendar = PlanningCalendar(horizon_start, horizon_weeks) if horizon_start and horizon_weeks else None
    prepared_activities: list[PreparedActivity] = []
    for activity in sorted(instance.activities, key=lambda item: item.activity_id):
        project = projects.get(activity.contract_number)
        if project is None or activity.activity_type != project.activity_type:
            continue
        try:
            route = topology.route_for(activity)
        except (KeyError, ValueError):
            findings.add(
                f"{activity.activity_id} has an unknown or malformed SEC working section.",
                rule="topology",
                table="activities",
                record=activity,
                field="start_location_id",
                activity_ids=(activity.activity_id,),
            )
            continue
        base = topology.base_locations(route)
        closure = topology.closure_locations(route, project)
        missing_base = tuple(sorted(base - set(supply)))
        if missing_base:
            findings.add(
                f"{activity.activity_id} footprint references locations absent from supply: {list(missing_base)}.",
                rule="topology",
                table="activities",
                record=activity,
                field="start_location_id",
                activity_ids=(activity.activity_id,),
                location_ids=missing_base,
            )
        missing_closure = tuple(sorted(closure - set(supply)))
        if missing_closure:
            findings.add(
                f"{activity.activity_id} closure footprint references locations absent from supply: {list(missing_closure)}.",
                rule="topology",
                table="activities",
                record=activity,
                field="start_location_id",
                activity_ids=(activity.activity_id,),
                location_ids=missing_closure,
            )
        if calendar is None:
            continue
        planned_week = calendar.planned_week(activity.planned_start_date)
        if planned_week < 1 or planned_week > calendar.horizon_weeks:
            findings.add(
                f"{activity.activity_id} planned_start_date {activity.planned_start_date} is outside the planning horizon.",
                table="activities",
                record=activity,
                field="planned_start_date",
                activity_ids=(activity.activity_id,),
            )
            continue
        candidate_weeks = tuple(range(planned_week, calendar.horizon_weeks + 1))
        if activity.total_accesses > len(candidate_weeks):
            findings.add(
                f"{activity.activity_id} needs {activity.total_accesses} accesses but only {len(candidate_weeks)} weeks remain after its planned start.",
                table="activities",
                record=activity,
                field="total_accesses",
                activity_ids=(activity.activity_id,),
            )
            continue
        prepared_activities.append(
            PreparedActivity(activity, project, route, base, closure, planned_week, candidate_weeks)
        )

    if findings.items or calendar is None:
        return PreparationResult(prepared=None, findings=tuple(findings.items))
    return PreparationResult(
        prepared=PreparedInstance(
            instance=instance,
            calendar=calendar,
            projects=projects,
            activities=tuple(prepared_activities),
            supply=supply,
        ),
        findings=(),
    )


def require_prepared(instance: InstanceBundle) -> PreparedInstance:
    """Return a complete prepared instance or raise all actionable findings."""

    result = prepare_instance(instance)
    if result.prepared is None:
        raise PreparationError(result.findings)
    return result.prepared
