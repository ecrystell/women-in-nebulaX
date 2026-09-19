"""OR-Tools CP-SAT model for the published PS1 railway access problem.

The model assigns access weeks, contract-local access nights, ECLO flags and a
legal possession slot at every occupied location.  It deliberately emits only
solutions produced by CP-SAT; the local validator remains an independent
post-solve gate.
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from ortools.sat.python import cp_model

from app.api.schemas import InputInstance, ScenarioChange
from app.domain.models import (
    AccessAssignment,
    AccessType,
    ContractResult,
    InstanceBundle,
    OccupancyAssignment,
    Scenario,
    ScenarioSchedule,
)
from app.exports.csv_writer import write_submission
from app.validation.preflight import _Preflight, validate_schedule


class SolveError(RuntimeError):
    """The instance is invalid or CP-SAT did not produce a complete schedule."""


class SolverError(SolveError):
    """Compatibility error exposed by the shared solver adapter."""


class SolverDependencyError(SolverError):
    """A required optimisation dependency is unavailable."""


def _sum(values):
    """Return a CP-SAT linear sum while handling an empty collection."""

    values = list(values)
    return sum(values) if values else 0


@dataclass(frozen=True)
class SolverConfig:
    max_time_seconds: float = 120.0
    workers: int = max(1, min(8, os.cpu_count() or 1))
    random_seed: int = 2026
    log_search_progress: bool = False


@dataclass(frozen=True)
class _ActivityFacts:
    locations: frozenset[str]
    closure: frozenset[str]
    line_codes: frozenset[str]
    planned_week: int


class CpSatRailSolver:
    """Build and solve one exact, scenario-specific CP-SAT model."""

    def __init__(self, config: SolverConfig | None = None) -> None:
        self.config = config or SolverConfig()
        self.last_status: str | None = None
        self.last_wall_time_seconds: float | None = None

    def solve(
        self,
        input_instance: InputInstance,
        scenario: Scenario,
        scenario_change: ScenarioChange | None = None,
    ) -> SimpleNamespace:
        # SimpleNamespace is intentionally structural: RunService's adapter
        # contract requires ``schedule`` and optional ``schedule_diff`` only.
        schedule = self.solve_bundle(input_instance.to_bundle(), scenario, scenario_change)
        return SimpleNamespace(schedule=schedule, schedule_diff=None)

    def solve_recovery(
        self,
        input_instance: InputInstance,
        scenario: Scenario,
        scenario_change: ScenarioChange,
        baseline: ScenarioSchedule,
    ) -> SimpleNamespace:
        schedule = self.solve_bundle(
            input_instance.to_bundle(), scenario, scenario_change, baseline=baseline
        )
        return SimpleNamespace(schedule=schedule, schedule_diff=None)

    def solve_bundle(
        self,
        instance: InstanceBundle,
        scenario: Scenario,
        scenario_change: ScenarioChange | None = None,
        *,
        baseline: ScenarioSchedule | None = None,
    ) -> ScenarioSchedule:
        scenario = Scenario(scenario)
        empty = ScenarioSchedule(
            scenario=scenario,
            access_assignments=[],
            occupancy_assignments=[],
            contract_results=[],
        )
        rules = _Preflight(instance, empty)
        rules.validate_input_references()
        if rules.violations:
            raise SolveError("invalid input: " + "; ".join(str(v["detail"]) for v in rules.violations[:5]))
        if rules.horizon_start is None or rules.horizon_weeks is None:
            raise SolveError("horizon_start and horizon_weeks are required")

        activities = {item.activity_id: item for item in instance.activities}
        projects = {item.contract_number: item for item in instance.projects}
        horizon = rules.horizon_weeks
        weeks = range(1, horizon + 1)
        facts: dict[str, _ActivityFacts] = {}
        eligible_by_location: dict[str, list[str]] = defaultdict(list)
        for activity in instance.activities:
            locations = frozenset(rules.base_locations(activity))
            if not locations:
                raise SolveError(f"{activity.activity_id} has no valid occupancy footprint")
            closure = frozenset(rules.closure_locations(activity))
            planned_week = rules.planned_week(activity.planned_start_date)
            if planned_week is None or planned_week > horizon:
                raise SolveError(f"{activity.activity_id} starts outside the planning horizon")
            lines = frozenset(location.split(":")[1] for location in closure)
            facts[activity.activity_id] = _ActivityFacts(locations, closure, lines, max(1, planned_week))
            for location in locations:
                eligible_by_location[location].append(activity.activity_id)

        supply = {item.location_id: item.supply_capacity for item in instance.location_supply}
        overrides = {
            (item.location_id, item.week): item.supply_capacity
            for item in (scenario_change.supply_overrides if scenario_change else [])
        }
        for location, week in overrides:
            if location not in supply or not 1 <= week <= horizon:
                raise SolveError(f"invalid supply override for {location}, week {week}")

        model = cp_model.CpModel()
        x: dict[tuple[str, int], cp_model.IntVar] = {}
        eclo: dict[tuple[str, int], cp_model.IntVar] = {}
        night: dict[tuple[str, int, int], cp_model.IntVar] = {}
        end_week: dict[str, cp_model.IntVar] = {}
        overrun_days: dict[str, cp_model.IntVar] = {}

        # Access assignment and workload conservation.  Scaling work units by
        # two keeps the model integral: a standard access yields 2, ECLO 3.
        for activity_id, activity in activities.items():
            candidate_weeks = range(facts[activity_id].planned_week, horizon + 1)
            project = projects[activity.contract_number]
            for week in weeks:
                x[activity_id, week] = model.NewBoolVar(f"x_{activity_id}_{week}")
                eclo[activity_id, week] = model.NewBoolVar(f"e_{activity_id}_{week}")
                model.Add(eclo[activity_id, week] <= x[activity_id, week])
                if week not in candidate_weeks:
                    model.Add(x[activity_id, week] == 0)
                if scenario == Scenario.A:
                    model.Add(eclo[activity_id, week] == 0)
                for access_night in range(1, project.number_of_maximum_access_per_week + 1):
                    night[activity_id, week, access_night] = model.NewBoolVar(
                        f"night_{activity_id}_{week}_{access_night}"
                    )
                model.Add(
                    sum(
                        night[activity_id, week, access_night]
                        for access_night in range(1, project.number_of_maximum_access_per_week + 1)
                    )
                    == x[activity_id, week]
                )
            delivered = 2 * sum(x[activity_id, week] for week in weeks) + sum(
                eclo[activity_id, week] for week in weeks
            )
            model.Add(delivered >= 2 * activity.total_accesses)
            # Prevent redundant access rows while allowing the unavoidable 0.5
            # unit overshoot caused by integral ECLO decisions.
            model.Add(delivered <= 2 * activity.total_accesses + 1)

            end_week[activity_id] = model.NewIntVar(1, horizon, f"end_{activity_id}")
            model.AddMaxEquality(
                end_week[activity_id],
                [week * x[activity_id, week] for week in weeks],
            )
            planned_offset = (project.planned_completion_date - rules.horizon_start).days
            max_overrun = max(0, horizon * 7 - 1 - planned_offset)
            overrun_days[activity_id] = model.NewIntVar(0, max_overrun, f"late_{activity_id}")
            model.AddMaxEquality(
                overrun_days[activity_id],
                [7 * end_week[activity_id] - 1 - planned_offset, 0],
            )
            if scenario == Scenario.B:
                model.Add(overrun_days[activity_id] == 0)

        # Contract/type nightly workfronts.  The selected night labels also
        # guarantee the published cap on distinct access-night values.
        by_contract_type: dict[tuple[str, str], list[str]] = defaultdict(list)
        for activity in instance.activities:
            by_contract_type[activity.contract_number, activity.activity_type].append(activity.activity_id)
        for (contract, _activity_type), member_ids in by_contract_type.items():
            project = projects[contract]
            for week in weeks:
                for access_night in range(1, project.number_of_maximum_access_per_week + 1):
                    model.Add(
                        sum(night[activity_id, week, access_night] for activity_id in member_ids)
                        <= project.number_of_workfronts
                    )

        baseline_access = {
            (item.activity_id, item.access_seq): item
            for item in (baseline.access_assignments if baseline else [])
        }
        if scenario_change and scenario_change.locked_placements and baseline is None:
            raise SolveError("locked placements require the referenced baseline schedule")
        if scenario_change:
            for key in scenario_change.locked_placements:
                assignment = baseline_access.get((key.activity_id, key.access_seq))
                if assignment is None:
                    raise SolveError(
                        f"locked placement {key.activity_id}/{key.access_seq} is absent from the baseline"
                    )
                activity = activities.get(key.activity_id)
                if activity is None:
                    raise SolveError(f"locked placement references unknown activity {key.activity_id}")
                project = projects[activity.contract_number]
                if assignment.access_night > project.number_of_maximum_access_per_week:
                    raise SolveError(f"baseline access night is invalid for {key.activity_id}")
                model.Add(x[key.activity_id, assignment.week] == 1)
                model.Add(
                    sum(x[key.activity_id, week] for week in range(1, assignment.week))
                    == key.access_seq - 1
                )
                model.Add(night[key.activity_id, assignment.week, assignment.access_night] == 1)
                model.Add(eclo[key.activity_id, assignment.week] == assignment.eclo)

        # Finish-to-start precedence is strict by week, including cross-contract
        # links.  Pairwise forbidden week combinations are strong and compact
        # for this small discrete horizon.
        for activity in instance.activities:
            predecessor = activity.predecessor_activity_id
            if not predecessor:
                continue
            for predecessor_week in weeks:
                for successor_week in range(1, predecessor_week + 1):
                    model.Add(
                        x[predecessor, predecessor_week] + x[activity.activity_id, successor_week] <= 1
                    )

        # A connected location footprint is packed into one legal possession in
        # a week.  This canonical grouping removes slot-label symmetry (the
        # largest source of search time) and matches the organiser diagnostic:
        # overlapping activities in different groups are closure violations.
        # Supply is still checked because a zero-capacity override makes the
        # location unavailable.  More than one possession is useful only for
        # spatially distinct footprints and is counted independently there.
        used: dict[tuple[str, int], cp_model.IntVar] = {}
        excess: dict[tuple[str, int], cp_model.IntVar] = {}

        for location, member_ids in eligible_by_location.items():
            for week in weeks:
                nominal = overrides.get((location, week), supply.get(location, 0))
                member_vars = [x[activity_id, week] for activity_id in member_ids]
                used[location, week] = model.NewBoolVar(f"used_{abs(hash(location))}_{week}")
                model.Add(sum(member_vars) >= used[location, week])
                model.Add(sum(member_vars) <= 4 * used[location, week])
                pm_vars = [
                    x[activity_id, week]
                    for activity_id in member_ids
                    if projects[activities[activity_id].contract_number].access_type == AccessType.PM
                ]
                pc_vars = [
                    x[activity_id, week]
                    for activity_id in member_ids
                    if projects[activities[activity_id].contract_number].access_type == AccessType.PC
                ]
                if pm_vars:
                    model.Add(sum(pm_vars) <= 1)
                    model.Add(sum(member_vars) <= 4 - 3 * sum(pm_vars))
                if pc_vars:
                    model.Add(sum(pc_vars) <= 1)
                if nominal == 0 and scenario == Scenario.A:
                    model.Add(used[location, week] == 0)
                excess[location, week] = model.NewBoolVar(f"excess_{abs(hash(location))}_{week}")
                if nominal == 0:
                    model.Add(excess[location, week] == used[location, week])
                else:
                    model.Add(excess[location, week] == 0)
                if scenario == Scenario.C and nominal == 0:
                    # The one published elastic possession is represented by
                    # this Boolean; no second group is emitted.
                    model.Add(used[location, week] <= 1)

        # The organiser reports a closure conflict when a scheduled activity is
        # inside another possession group's derived closure.  Activities with a
        # common occupied location may coexist only by sharing a legal slot at
        # every common location; disjoint works whose closures touch cannot.
        activity_ids = sorted(activities)
        for index, left in enumerate(activity_ids):
            for right in activity_ids[index + 1 :]:
                left_hits_right = facts[left].locations & facts[right].closure
                right_hits_left = facts[right].locations & facts[left].closure
                if not left_hits_right and not right_hits_left:
                    continue
                common = facts[left].locations & facts[right].locations
                for week in weeks:
                    if not common:
                        model.Add(x[left, week] + x[right, week] <= 1)
                        continue
                    # Common locations use the canonical shared possession and
                    # are therefore exempt from each other's buffers.

        # Scenario C permits one independently chosen two-week ECLO window per
        # affected line.  A Live interchange closure naturally belongs to both.
        if scenario == Scenario.C:
            window_start = {
                line.line_code: model.NewIntVar(1, horizon, f"eclo_window_{line.line_code}")
                for line in instance.lines
            }
            for activity_id in activity_ids:
                for week in weeks:
                    for line in facts[activity_id].line_codes:
                        model.Add(window_start[line] <= week).OnlyEnforceIf(eclo[activity_id, week])
                        model.Add(week <= window_start[line] + 1).OnlyEnforceIf(eclo[activity_id, week])

        # Official objective, integer-scaled by ten to preserve the 0.2/0.3
        # activity-priority nudges exactly.  A tiny lexicographic tie-breaker
        # favours fewer accesses/possessions and earlier completion without ever
        # worsening the published score.
        weighted_overrun_terms = []
        for activity_id, activity in activities.items():
            project = projects[activity.contract_number]
            base = {1: 100, 2: 10, 3: 1}[project.contract_priority]
            nudge_tenths = {1: 3, 2: 2, 3: 0}[activity.activity_priority]
            weighted_overrun_terms.append(base * (10 + nudge_tenths) * overrun_days[activity_id])
        primary_terms = []
        if scenario != Scenario.B:
            primary_terms.extend(weighted_overrun_terms)
        if scenario != Scenario.A:
            primary_terms.append(70 * sum(excess.values()))
            primary_terms.append(50 * sum(eclo.values()))
        primary = sum(primary_terms)
        compactness = sum(x.values()) + sum(used.values()) + sum(end_week.values())
        compactness_bound = len(x) + len(used) + horizon * len(end_week) + 1
        changed: list[cp_model.IntVar] = []
        if baseline:
            for assignment in baseline.access_assignments:
                if assignment.activity_id not in activities or not 1 <= assignment.week <= horizon:
                    continue
                project = projects[activities[assignment.activity_id].contract_number]
                if assignment.access_night > project.number_of_maximum_access_per_week:
                    continue
                variable = model.NewBoolVar(
                    f"changed_{assignment.activity_id}_{assignment.access_seq}"
                )
                model.Add(variable >= 1 - x[assignment.activity_id, assignment.week])
                model.Add(
                    variable
                    >= 1 - night[assignment.activity_id, assignment.week, assignment.access_night]
                )
                if assignment.eclo:
                    model.Add(variable >= 1 - eclo[assignment.activity_id, assignment.week])
                else:
                    model.Add(variable >= eclo[assignment.activity_id, assignment.week])
                changed.append(variable)
        secondary = compactness + compactness_bound * sum(changed)
        secondary_bound = compactness_bound * (len(changed) + 1)
        model.Minimize(primary * secondary_bound + secondary)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.config.max_time_seconds
        solver.parameters.num_search_workers = self.config.workers
        solver.parameters.random_seed = self.config.random_seed
        solver.parameters.log_search_progress = self.config.log_search_progress
        solver.parameters.cp_model_presolve = True
        solver.parameters.symmetry_level = 2
        status = solver.Solve(model)
        self.last_status = solver.StatusName(status)
        self.last_wall_time_seconds = solver.WallTime()
        if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            raise SolveError(
                f"CP-SAT returned {solver.StatusName(status)} after {solver.WallTime():.2f}s; "
                "no schedule may be exported"
            )

        access_rows: list[AccessAssignment] = []
        occupancy_rows: list[OccupancyAssignment] = []
        for activity_id in activity_ids:
            sequence = 0
            for week in weeks:
                if not solver.BooleanValue(x[activity_id, week]):
                    continue
                sequence += 1
                project = projects[activities[activity_id].contract_number]
                selected_night = next(
                    value
                    for value in range(1, project.number_of_maximum_access_per_week + 1)
                    if solver.BooleanValue(night[activity_id, week, value])
                )
                access_rows.append(
                    AccessAssignment(
                        activity_id=activity_id,
                        access_seq=sequence,
                        week=week,
                        eclo=int(solver.BooleanValue(eclo[activity_id, week])),
                        access_night=selected_night,
                    )
                )
                for location in sorted(facts[activity_id].locations):
                    occupancy_rows.append(
                        OccupancyAssignment(
                            activity_id=activity_id,
                            week=week,
                            location_id=location,
                            co_share_group="p1",
                        )
                    )

        result_rows: list[ContractResult] = []
        activities_by_contract: dict[str, list[str]] = defaultdict(list)
        for activity in instance.activities:
            activities_by_contract[activity.contract_number].append(activity.activity_id)
        for contract_number, project in projects.items():
            completion_week = max(solver.Value(end_week[item]) for item in activities_by_contract[contract_number])
            completion_date = rules.horizon_start + timedelta(days=completion_week * 7 - 1)
            result_rows.append(
                ContractResult(
                    scenario=scenario,
                    contract_number=contract_number,
                    simulated_completion_date=completion_date,
                    overrun_days=max(0, (completion_date - project.planned_completion_date).days),
                )
            )

        schedule = ScenarioSchedule(
            scenario=scenario,
            access_assignments=access_rows,
            occupancy_assignments=occupancy_rows,
            contract_results=result_rows,
        )
        report = validate_schedule(instance, schedule, overrides)
        if report.hard_violations:
            sample = "; ".join(str(item["detail"]) for item in report.hard_violations[:5])
            raise SolveError(f"internal post-solve validation failed: {sample}")
        return schedule


@dataclass(frozen=True)
class SolveDiagnostics:
    status: str
    objective_value_scaled: float
    best_objective_bound_scaled: float
    relative_gap: float
    weighted_score: float
    solve_seconds: float
    activity_count: int
    scheduled_access_rows: int
    occupancy_rows: int
    contract_count: int


@dataclass(frozen=True)
class SolveResult:
    schedule: ScenarioSchedule
    diagnostics: SolveDiagnostics


class ScenarioASolver:
    """Compatibility facade for the API/CLI Scenario A solver contract."""

    def __init__(
        self,
        *,
        time_limit_seconds: float = 60.0,
        random_seed: int = 0,
        num_search_workers: int = 8,
        initial_schedule: ScenarioSchedule | None = None,
    ) -> None:
        self.config = SolverConfig(
            max_time_seconds=time_limit_seconds,
            workers=num_search_workers,
            random_seed=random_seed,
        )
        self.initial_schedule = initial_schedule
        self.last_result: SolveResult | None = None

    def solve(
        self,
        instance: InstanceBundle,
        scenario: Scenario = Scenario.A,
        scenario_change: ScenarioChange | None = None,
    ) -> ScenarioSchedule:
        return self.solve_with_diagnostics(instance, scenario, scenario_change).schedule

    def solve_with_diagnostics(
        self,
        instance: InstanceBundle,
        scenario: Scenario = Scenario.A,
        scenario_change: ScenarioChange | None = None,
    ) -> SolveResult:
        from app.domain.preprocessing import require_prepared

        return self.solve_prepared_with_diagnostics(
            require_prepared(instance), scenario, scenario_change
        )

    def solve_prepared_with_diagnostics(
        self,
        prepared,
        scenario: Scenario = Scenario.A,
        scenario_change: ScenarioChange | None = None,
    ) -> SolveResult:
        if scenario is not Scenario.A:
            raise SolverError(
                f"ScenarioASolver requires Scenario A, received {scenario.value}."
            )
        solver = CpSatRailSolver(self.config)
        try:
            schedule = solver.solve_bundle(
                prepared.instance,
                scenario,
                scenario_change,
                baseline=self.initial_schedule,
            )
        except SolveError as error:
            raise SolverError(str(error)) from error

        from app.solver.scoring import scenario_a_score

        score = float(
            scenario_a_score(
                prepared.instance, schedule, calendar=prepared.calendar
            )
        )
        scaled = score * 10
        status = solver.last_status or "FEASIBLE"
        diagnostics = SolveDiagnostics(
            status=status,
            objective_value_scaled=scaled,
            best_objective_bound_scaled=scaled if status == "OPTIMAL" else 0.0,
            relative_gap=0.0 if status == "OPTIMAL" else 1.0,
            weighted_score=score,
            solve_seconds=float(solver.last_wall_time_seconds or 0.0),
            activity_count=len(prepared.activities),
            scheduled_access_rows=len(schedule.access_assignments),
            occupancy_rows=len(schedule.occupancy_assignments),
            contract_count=len(schedule.contract_results),
        )
        result = SolveResult(schedule=schedule, diagnostics=diagnostics)
        self.last_result = result
        return result


def main() -> int:
    from app.ingestion.csv_loader import load_instance

    parser = argparse.ArgumentParser(description="Solve a PS1 instance with OR-Tools CP-SAT.")
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--scenario", type=Scenario, required=True, choices=list(Scenario))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--time-limit", type=float, default=120.0)
    parser.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 1)))
    parser.add_argument("--log-search", action="store_true")
    args = parser.parse_args()
    solver = CpSatRailSolver(
        SolverConfig(
            max_time_seconds=args.time_limit,
            workers=args.workers,
            log_search_progress=args.log_search,
        )
    )
    try:
        schedule = solver.solve_bundle(load_instance(args.instance), args.scenario)
    except SolveError as error:
        parser.error(str(error))
    write_submission(schedule, args.output)
    report = validate_schedule(load_instance(args.instance), schedule)
    print(
        f"scenario={args.scenario.value} status={solver.last_status} "
        f"wall_time={solver.last_wall_time_seconds:.2f}s accesses={len(schedule.access_assignments)} "
        f"score={report.soft_scores.get('objective_score')} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
