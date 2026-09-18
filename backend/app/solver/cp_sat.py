"""Shared CP-SAT model with the Scenario A policy enabled."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

try:  # Keep ingestion/API imports usable when optional solver dependencies are absent.
    from ortools.sat.python import cp_model
except ImportError:  # pragma: no cover - exercised only in dependency-free environments.
    cp_model = None  # type: ignore[assignment]

from ..domain.models import (
    AccessAssignment,
    ContractResult,
    InstanceBundle,
    OccupancyAssignment,
    Scenario,
    ScenarioSchedule,
)
from .policy import ScenarioPolicy, policy_for
from .scoring import scenario_a_score
from .topology import PreparedActivity, PreparedInstance, SolverInputError, prepare_instance


class SolverDependencyError(RuntimeError):
    """OR-Tools is not installed in the active Python environment."""


class SolverError(RuntimeError):
    """The model could not produce a valid CP-SAT candidate."""


@dataclass(frozen=True)
class SolveDiagnostics:
    status: str
    objective_value_scaled: float
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


@dataclass
class _ModelArtifacts:
    model: Any
    prepared: PreparedInstance
    policy: ScenarioPolicy
    assignments: dict[tuple[str, int, int], Any]
    activity_week: dict[tuple[str, int], Any]
    group_assignments: dict[tuple[str, str, int, int], Any]
    first_week: dict[str, Any]
    last_week: dict[str, Any]
    overrun_days: dict[str, Any]


def _sum(values: list[Any]) -> Any:
    """Return a CP-SAT-compatible sum, including for an empty list."""

    return sum(values, 0)


class ScenarioASolver:
    """Solve one input bundle under the strict-supply Scenario A policy."""

    def __init__(
        self,
        *,
        time_limit_seconds: float = 60.0,
        random_seed: int = 0,
        num_search_workers: int = 1,
    ) -> None:
        self.time_limit_seconds = time_limit_seconds
        self.random_seed = random_seed
        self.num_search_workers = num_search_workers
        self.last_result: SolveResult | None = None

    def solve(
        self,
        instance: InstanceBundle,
        scenario: Scenario = Scenario.A,
        scenario_change: object | None = None,
    ) -> ScenarioSchedule:
        return self.solve_with_diagnostics(instance, scenario, scenario_change).schedule

    def solve_with_diagnostics(
        self,
        instance: InstanceBundle,
        scenario: Scenario = Scenario.A,
        scenario_change: object | None = None,
    ) -> SolveResult:
        if scenario is not Scenario.A:
            policy_for(scenario)  # raises the central unsupported-scenario error
        if scenario_change is not None:
            raise SolverError(
                "Disruption recovery is not implemented in the Scenario A core solver yet."
            )
        if cp_model is None:
            raise SolverDependencyError(
                "OR-Tools is required for the CP-SAT solver; install requirements.txt first."
            )

        prepared = prepare_instance(instance)
        policy = policy_for(scenario)
        artifacts = self._build_model(prepared, policy)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.time_limit_seconds
        solver.parameters.random_seed = self.random_seed
        solver.parameters.num_search_workers = self.num_search_workers
        solver.parameters.log_search_progress = False

        started = time.perf_counter()
        status = solver.Solve(artifacts.model)
        elapsed = time.perf_counter() - started
        status_name = solver.StatusName(status)
        if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            raise SolverError(
                f"Scenario A CP-SAT solve ended with {status_name}; no schedule was extracted. "
                "Increase the time limit or inspect the input/topology diagnostics."
            )

        schedule = self._extract_schedule(artifacts, solver)
        weighted_score = scenario_a_score(instance, schedule)
        diagnostics = SolveDiagnostics(
            status=status_name,
            objective_value_scaled=solver.ObjectiveValue(),
            weighted_score=weighted_score,
            solve_seconds=elapsed,
            activity_count=len(prepared.activities),
            scheduled_access_rows=len(schedule.access_assignments),
            occupancy_rows=len(schedule.occupancy_assignments),
            contract_count=len(schedule.contract_results),
        )
        result = SolveResult(schedule=schedule, diagnostics=diagnostics)
        self.last_result = result
        return result

    def _build_model(
        self, prepared: PreparedInstance, policy: ScenarioPolicy
    ) -> _ModelArtifacts:
        model = cp_model.CpModel()
        horizon = prepared.calendar.horizon_weeks
        activities = prepared.activities
        activity_by_id = {item.activity.activity_id: item for item in activities}

        assignments: dict[tuple[str, int, int], Any] = {}
        activity_week: dict[tuple[str, int], Any] = {}
        group_assignments: dict[tuple[str, str, int, int], Any] = {}

        # Every activity receives exactly its declared number of standard
        # accesses.  A week has at most one access for one activity, while the
        # access-night index remains local to contract + activity type + week.
        for item in activities:
            activity_id = item.activity.activity_id
            max_night = item.project.number_of_maximum_access_per_week
            week_variables: list[Any] = []
            for week in item.candidate_weeks:
                week_var = model.NewBoolVar(f"access_{activity_id}_w{week}")
                activity_week[(activity_id, week)] = week_var
                week_variables.append(week_var)
                night_variables = []
                for night in range(1, max_night + 1):
                    assignment = model.NewBoolVar(
                        f"access_{activity_id}_w{week}_n{night}"
                    )
                    assignments[(activity_id, week, night)] = assignment
                    night_variables.append(assignment)
                model.Add(_sum(night_variables) == week_var)
            model.Add(_sum(week_variables) == item.activity.total_accesses)

        # Weekly allocation and workfront constraints.  The used-night flags
        # are deliberately contract/type/week local, matching the CSV contract.
        by_contract_type_week: dict[tuple[str, str, int], list[PreparedActivity]] = defaultdict(list)
        for item in activities:
            for week in item.candidate_weeks:
                by_contract_type_week[
                    (item.activity.contract_number, item.activity.activity_type, week)
                ].append(item)

        for (contract, activity_type, week), members in sorted(by_contract_type_week.items()):
            project = prepared.projects[contract]
            for night in range(1, project.number_of_maximum_access_per_week + 1):
                flags = [
                    assignments[(item.activity.activity_id, week, night)]
                    for item in members
                ]
                used = model.NewBoolVar(
                    f"used_night_{contract}_{activity_type}_w{week}_n{night}"
                )
                for flag in flags:
                    model.Add(flag <= used)
                model.Add(used <= _sum(flags))
                model.Add(_sum(flags) <= project.number_of_workfronts)

        # A location has at most supply_capacity possession groups in a week.
        # Internal group assignments cover the complete closure footprint.  We
        # emit only base-location rows, because the official occupancy schema
        # describes where the activity works, not hidden buffer closures.
        for item in activities:
            activity_id = item.activity.activity_id
            for location_id in sorted(item.closure_locations):
                capacity = prepared.supply[location_id]
                for week in item.candidate_weeks:
                    group_variables = []
                    for group in range(capacity):
                        variable = model.NewBoolVar(
                            f"group_{activity_id}_{location_id}_w{week}_g{group}"
                        )
                        group_assignments[(activity_id, location_id, week, group)] = variable
                        group_variables.append(variable)
                    week_var = activity_week[(activity_id, week)]
                    if group_variables:
                        model.Add(_sum(group_variables) == week_var)
                    else:
                        model.Add(week_var == 0)

        members_by_location: dict[str, list[PreparedActivity]] = defaultdict(list)
        for item in activities:
            for location_id in sorted(item.closure_locations):
                members_by_location[location_id].append(item)

        for location_id, members in sorted(members_by_location.items()):
            capacity = prepared.supply[location_id]
            for week in range(1, horizon + 1):
                for group in range(capacity):
                    group_members = [
                        item
                        for item in members
                        if week in item.candidate_weeks
                    ]
                    pm_count = _sum(
                        [
                            group_assignments[(item.activity.activity_id, location_id, week, group)]
                            for item in group_members
                            if item.project.access_type.value == "PM"
                        ]
                    )
                    pc_count = _sum(
                        [
                            group_assignments[(item.activity.activity_id, location_id, week, group)]
                            for item in group_members
                            if item.project.access_type.value == "PC"
                        ]
                    )
                    c_count = _sum(
                        [
                            group_assignments[(item.activity.activity_id, location_id, week, group)]
                            for item in group_members
                            if item.project.access_type.value == "C"
                        ]
                    )
                    model.Add(pm_count <= 1)
                    model.Add(pc_count <= 1)
                    model.Add(c_count <= 4)
                    # PM must be alone; otherwise PC + up to three C or up to
                    # four C is legal.  With no PM, the inequality below gives
                    # PC + C <= 4, hence at most three C beside one PC.
                    model.Add(4 * pm_count + pc_count + c_count <= 4)

        # Different internal groups represent separate possession slots within
        # the week.  A closure may share a slot only when the two activities are
        # proven to be one legal co-sharing possession at a common base
        # location.  This is the strongest closure rule expressible without
        # inventing a global access-night identifier (the published
        # `access_night` is contract/type/week-local).
        for left_index, left in enumerate(activities):
            left_id = left.activity.activity_id
            for right in activities[left_index + 1 :]:
                right_id = right.activity.activity_id
                common_base = left.base_locations & right.base_locations
                shared_types = {
                    left.project.access_type.value,
                    right.project.access_type.value,
                }
                can_share = shared_types in ({"C"}, {"C", "PC"})
                common_closure = left.closure_locations & right.closure_locations
                if not common_closure:
                    continue
                common_weeks = sorted(set(left.candidate_weeks) & set(right.candidate_weeks))
                for week in common_weeks:
                    left_week = activity_week[(left_id, week)]
                    right_week = activity_week[(right_id, week)]
                    same_possession = model.NewBoolVar(
                        f"same_possession_{left_id}_{right_id}_w{week}"
                    )
                    model.Add(same_possession <= left_week)
                    model.Add(same_possession <= right_week)
                    same_base_flags = []
                    if can_share:
                        for location_id in sorted(common_base):
                            capacity = prepared.supply[location_id]
                            for group in range(capacity):
                                left_group = group_assignments[
                                    (left_id, location_id, week, group)
                                ]
                                right_group = group_assignments[
                                    (right_id, location_id, week, group)
                                ]
                                same_base = model.NewBoolVar(
                                    f"same_base_{left_id}_{right_id}_{location_id}_w{week}_g{group}"
                                )
                                model.Add(same_base <= left_group)
                                model.Add(same_base <= right_group)
                                model.Add(same_base >= left_group + right_group - 1)
                                same_base_flags.append(same_base)
                    for flag in same_base_flags:
                        model.Add(same_possession >= flag)
                    model.Add(same_possession <= _sum(same_base_flags))

                    for location_id in sorted(common_closure):
                        capacity = prepared.supply[location_id]
                        for group in range(capacity):
                            left_group = group_assignments[
                                (left_id, location_id, week, group)
                            ]
                            right_group = group_assignments[
                                (right_id, location_id, week, group)
                            ]
                            # Without a proven shared base possession, two
                            # activities may not occupy the same closure slot.
                            model.Add(left_group + right_group <= 1 + same_possession)

        first_week: dict[str, Any] = {}
        last_week: dict[str, Any] = {}
        overrun_days: dict[str, Any] = {}
        objective_terms: list[Any] = []
        scaled_contract_weight = {1: 1000, 2: 100, 3: 10}
        scaled_activity_nudge = {1: 3, 2: 2, 3: 0}

        for item in activities:
            activity_id = item.activity.activity_id
            first_values = []
            last_values = []
            for week in item.candidate_weeks:
                access = activity_week[(activity_id, week)]
                first_value = model.NewIntVar(1, horizon + 1, f"first_if_{activity_id}_w{week}")
                last_value = model.NewIntVar(0, horizon, f"last_if_{activity_id}_w{week}")
                model.Add(first_value == week).OnlyEnforceIf(access)
                model.Add(first_value == horizon + 1).OnlyEnforceIf(access.Not())
                model.Add(last_value == week).OnlyEnforceIf(access)
                model.Add(last_value == 0).OnlyEnforceIf(access.Not())
                first_values.append(first_value)
                last_values.append(last_value)

            first = model.NewIntVar(1, horizon, f"first_week_{activity_id}")
            last = model.NewIntVar(1, horizon, f"last_week_{activity_id}")
            model.AddMinEquality(first, first_values)
            model.AddMaxEquality(last, last_values)
            first_week[activity_id] = first
            last_week[activity_id] = last

            overrun_table = [0]
            for week in range(1, horizon + 1):
                overrun_table.append(
                    max(
                        0,
                        (
                            prepared.calendar.week_end(week)
                            - item.project.planned_completion_date
                        ).days,
                    )
                )
            overrun = model.NewIntVar(0, max(overrun_table), f"overrun_{activity_id}")
            model.AddElement(last, overrun_table, overrun)
            overrun_days[activity_id] = overrun

            base_weight = scaled_contract_weight[item.project.contract_priority]
            nudge = scaled_activity_nudge[item.activity.activity_priority]
            objective_terms.append((base_weight + base_weight * nudge // 10) * overrun)

        # Predecessor finish-to-start is strictly later by week, including
        # cross-contract predecessor references.
        for item in activities:
            predecessor = item.activity.predecessor_activity_id
            if predecessor:
                model.Add(last_week[predecessor] + 1 <= first_week[item.activity.activity_id])

        model.Minimize(_sum(objective_terms))
        return _ModelArtifacts(
            model=model,
            prepared=prepared,
            policy=policy,
            assignments=assignments,
            activity_week=activity_week,
            group_assignments=group_assignments,
            first_week=first_week,
            last_week=last_week,
            overrun_days=overrun_days,
        )

    def _extract_schedule(self, artifacts: _ModelArtifacts, solver: Any) -> ScenarioSchedule:
        prepared = artifacts.prepared
        access_assignments: list[AccessAssignment] = []
        occupancy_assignments: list[OccupancyAssignment] = []
        selected_weeks_by_activity: dict[str, list[int]] = {}

        for item in prepared.activities:
            activity_id = item.activity.activity_id
            selected: list[tuple[int, int]] = []
            for week in item.candidate_weeks:
                for night in range(1, item.project.number_of_maximum_access_per_week + 1):
                    variable = artifacts.assignments[(activity_id, week, night)]
                    if solver.Value(variable):
                        selected.append((week, night))
            selected.sort()
            if len(selected) != item.activity.total_accesses:
                raise SolverError(
                    f"internal extraction error: {activity_id} has {len(selected)} accesses, "
                    f"expected {item.activity.total_accesses}."
                )
            selected_weeks_by_activity[activity_id] = [week for week, _ in selected]
            for access_seq, (week, night) in enumerate(selected, start=1):
                access_assignments.append(
                    AccessAssignment(
                        activity_id=activity_id,
                        access_seq=access_seq,
                        week=week,
                        eclo=0,
                        access_night=night,
                    )
                )
                for location_id in sorted(item.base_locations):
                    capacity = prepared.supply[location_id]
                    selected_group = next(
                        (
                            group
                            for group in range(capacity)
                            if solver.Value(
                                artifacts.group_assignments[
                                    (activity_id, location_id, week, group)
                                ]
                            )
                        ),
                        None,
                    )
                    if selected_group is None:
                        raise SolverError(
                            f"internal extraction error: no possession group for {activity_id}, "
                            f"{location_id}, week {week}."
                        )
                    occupancy_assignments.append(
                        OccupancyAssignment(
                            activity_id=activity_id,
                            week=week,
                            location_id=location_id,
                            co_share_group=f"p{selected_group + 1}",
                        )
                    )

        completion_by_contract: dict[str, Any] = {}
        for item in prepared.activities:
            weeks = selected_weeks_by_activity[item.activity.activity_id]
            completion = prepared.calendar.week_end(max(weeks))
            previous = completion_by_contract.get(item.activity.contract_number)
            completion_by_contract[item.activity.contract_number] = (
                completion if previous is None else max(previous, completion)
            )

        contract_results: list[ContractResult] = []
        for project in sorted(prepared.projects.values(), key=lambda item: item.contract_number):
            completion = completion_by_contract.get(project.contract_number)
            if completion is None:
                raise SolverInputError(
                    f"contract {project.contract_number} has no activities and cannot produce RESULTS.csv."
                )
            contract_results.append(
                ContractResult(
                    scenario=Scenario.A,
                    contract_number=project.contract_number,
                    simulated_completion_date=completion,
                    overrun_days=max(0, (completion - project.planned_completion_date).days),
                )
            )

        access_assignments.sort(key=lambda item: (item.activity_id, item.access_seq))
        occupancy_assignments.sort(
            key=lambda item: (item.activity_id, item.week, item.location_id)
        )
        return ScenarioSchedule(
            scenario=Scenario.A,
            access_assignments=access_assignments,
            occupancy_assignments=occupancy_assignments,
            contract_results=contract_results,
        )
