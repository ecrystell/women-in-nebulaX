"""Scenario C CP-SAT solver.

This module is intentionally separate from ``cp_sat.py`` so Scenario A's
working model and output remain unchanged.  It uses the same prepared
topology, canonical schedule, and diagnostics contracts while adding only the
published Scenario C policy: ECLO, one soft excess possession per
location-week, and the two-week per-line ECLO window.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .cp_sat import (
    SolverDependencyError,
    SolverError,
    SolveDiagnostics,
    SolveResult,
    _sum,
    cp_model,
)
from .policy import ScenarioPolicy, policy_for
from .scoring import scenario_c_score
from ..domain.models import (
    AccessAssignment,
    ContractResult,
    InstanceBundle,
    OccupancyAssignment,
    Scenario,
    ScenarioSchedule,
)
from ..domain.preprocessing import PreparedActivity, PreparedInstance, require_prepared


@dataclass
class _ScenarioCArtifacts:
    model: Any
    prepared: PreparedInstance
    policy: ScenarioPolicy
    assignments: dict[tuple[str, int, int, int], Any]
    activity_week: dict[tuple[str, int], Any]
    activity_night: dict[tuple[str, int, int], Any]
    eclo_week: dict[tuple[str, int], Any]
    physical_night: dict[tuple[str, int], Any]
    group_assignments: dict[tuple[str, str, int, int], Any]
    first_week: dict[str, Any]
    last_week: dict[str, Any]


class ScenarioCSolver:
    """Solve one input bundle under the published Scenario C policy."""

    def __init__(
        self,
        *,
        time_limit_seconds: float = 60.0,
        random_seed: int = 0,
        num_search_workers: int = 8,
        initial_schedule: ScenarioSchedule | None = None,
    ) -> None:
        self.time_limit_seconds = time_limit_seconds
        self.random_seed = random_seed
        self.num_search_workers = num_search_workers
        self.initial_schedule = initial_schedule
        self.last_result: SolveResult | None = None

    def solve(
        self,
        instance: InstanceBundle,
        scenario: Scenario = Scenario.C,
        scenario_change: object | None = None,
    ) -> ScenarioSchedule:
        return self.solve_with_diagnostics(instance, scenario, scenario_change).schedule

    def solve_with_diagnostics(
        self,
        instance: InstanceBundle,
        scenario: Scenario = Scenario.C,
        scenario_change: object | None = None,
    ) -> SolveResult:
        if scenario is not Scenario.C:
            raise SolverError(f"ScenarioCSolver requires Scenario C, received {scenario.value}.")
        if scenario_change is not None:
            raise SolverError("Disruption recovery is not implemented in the Scenario C core solver yet.")
        return self.solve_prepared_with_diagnostics(require_prepared(instance), scenario, scenario_change)

    def solve_prepared_with_diagnostics(
        self,
        prepared: PreparedInstance,
        scenario: Scenario = Scenario.C,
        scenario_change: object | None = None,
    ) -> SolveResult:
        if scenario is not Scenario.C:
            raise SolverError(f"ScenarioCSolver requires Scenario C, received {scenario.value}.")
        if scenario_change is not None:
            raise SolverError("Disruption recovery is not implemented in the Scenario C core solver yet.")
        if cp_model is None:
            raise SolverDependencyError(
                "OR-Tools is required for the CP-SAT solver; install requirements.txt first."
            )

        policy = policy_for(Scenario.C)
        seed_elapsed = 0.0
        main_time_limit = self.time_limit_seconds
        seed_artifacts = None
        seed_solver = None
        seed_status = None
        if self.initial_schedule is not None:
            # First reconstruct the internal closure/group state omitted from
            # the three public CSVs while holding the validated incumbent's
            # visible decisions fixed. A complete CP-SAT solution is a much
            # stronger warm start than a partial CSV hint.
            seed_artifacts = self._build_model(prepared, policy)
            self._apply_schedule_hint(
                seed_artifacts, self.initial_schedule, fix=True
            )
            seed_solver = cp_model.CpSolver()
            seed_limit = min(30.0, max(5.0, self.time_limit_seconds * 0.25))
            seed_solver.parameters.max_time_in_seconds = seed_limit
            seed_solver.parameters.random_seed = self.random_seed
            seed_solver.parameters.num_search_workers = self.num_search_workers
            seed_solver.parameters.stop_after_first_solution = True
            seed_started = time.perf_counter()
            seed_status = seed_solver.Solve(seed_artifacts.model)
            seed_elapsed = time.perf_counter() - seed_started

            artifacts = self._build_model(prepared, policy)
            if seed_status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
                source_count = len(seed_artifacts.model.Proto().variables)
                target_count = len(artifacts.model.Proto().variables)
                if source_count != target_count:
                    raise SolverError(
                        "Scenario C warm-start models have inconsistent variable layouts."
                    )
                for index in range(source_count):
                    source = seed_artifacts.model.GetIntVarFromProtoIndex(index)
                    target = artifacts.model.GetIntVarFromProtoIndex(index)
                    artifacts.model.AddHint(target, seed_solver.Value(source))
                # The time budget is wall-clock solve time, not the maximum
                # seed allowance.  Reuse any seed time that CP-SAT did not
                # consume so the unrestricted proof search is not shortened
                # unnecessarily.
                main_time_limit = max(1.0, self.time_limit_seconds - seed_elapsed)
            else:
                self._apply_schedule_hint(artifacts, self.initial_schedule)
        else:
            artifacts = self._build_model(prepared, policy)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = main_time_limit
        solver.parameters.random_seed = self.random_seed
        solver.parameters.num_search_workers = self.num_search_workers
        solver.parameters.log_search_progress = False

        started = time.perf_counter()
        status = solver.Solve(artifacts.model)
        elapsed = seed_elapsed + time.perf_counter() - started
        status_name = solver.StatusName(status)
        unrestricted_bound = solver.BestObjectiveBound()
        used_seed_fallback = False
        if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            # A reconstructed incumbent is itself a complete CP-SAT solution
            # to the same model with only its visible decisions fixed.  Keep
            # it as a valid FEASIBLE fallback when the unrestricted proof
            # search spends its whole budget in presolve/search without
            # reporting an incumbent.
            if seed_status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
                artifacts = seed_artifacts
                solver = seed_solver
                status = cp_model.FEASIBLE
                status_name = "FEASIBLE"
                used_seed_fallback = True
            else:
                raise SolverError(
                    f"Scenario C CP-SAT solve ended with {status_name}; no schedule was extracted. "
                    "Increase the time limit or inspect the input/topology diagnostics."
                )

        schedule = self._extract_schedule(artifacts, solver)
        score = scenario_c_score(prepared.instance, schedule, calendar=prepared.calendar)
        objective_value = solver.ObjectiveValue()
        best_bound = unrestricted_bound if used_seed_fallback else solver.BestObjectiveBound()
        # A feasible reconstructed incumbent plus a matching lower bound from
        # the unrestricted model is a valid optimality proof even if that
        # unrestricted search did not emit its own incumbent.
        if used_seed_fallback and abs(objective_value - best_bound) < 1e-6:
            status_name = "OPTIMAL"
        diagnostics = SolveDiagnostics(
            status=status_name,
            objective_value_scaled=objective_value,
            best_objective_bound_scaled=best_bound,
            relative_gap=(
                0.0
                if objective_value == 0
                else max(
                    0.0,
                    (objective_value - best_bound)
                    / abs(objective_value),
                )
            ),
            weighted_score=score,
            solve_seconds=elapsed,
            activity_count=len(prepared.activities),
            scheduled_access_rows=len(schedule.access_assignments),
            occupancy_rows=len(schedule.occupancy_assignments),
            contract_count=len(schedule.contract_results),
        )
        result = SolveResult(schedule=schedule, diagnostics=diagnostics)
        self.last_result = result
        return result

    def _apply_schedule_hint(
        self,
        artifacts: _ScenarioCArtifacts,
        schedule: ScenarioSchedule,
        *,
        fix: bool = False,
    ) -> None:
        """Warm-start Scenario C from a previously validated CP-SAT output."""

        if schedule.scenario is not Scenario.C:
            return

        def apply_value(variable: Any, value: int) -> None:
            if fix:
                artifacts.model.Add(variable == value)
            else:
                artifacts.model.AddHint(variable, value)

        assignments_by_activity: dict[str, list[AccessAssignment]] = defaultdict(list)
        for assignment in schedule.access_assignments:
            assignments_by_activity[assignment.activity_id].append(assignment)
        selected: set[tuple[str, int, int, int]] = set()
        for item in artifacts.prepared.activities:
            delivered_half_units = 0
            target_half_units = 2 * item.activity.total_accesses
            for assignment in sorted(
                assignments_by_activity.get(item.activity.activity_id, []),
                key=lambda value: (value.week, value.access_night, value.eclo),
            ):
                if delivered_half_units >= target_half_units:
                    break
                selected.add(
                    (
                        assignment.activity_id,
                        assignment.week,
                        assignment.access_night,
                        assignment.eclo,
                    )
                )
                delivered_half_units += 3 if assignment.eclo else 2
        selected_weeks = {
            (activity_id, week) for activity_id, week, _night, _eclo in selected
        }
        selected_nights = {
            (activity_id, week, night)
            for activity_id, week, night, _eclo in selected
        }
        selected_eclo_weeks = {
            (activity_id, week)
            for activity_id, week, _night, eclo in selected
            if eclo
        }
        for key, variable in artifacts.assignments.items():
            apply_value(variable, int(key in selected))
        for key, variable in artifacts.activity_week.items():
            apply_value(variable, int(key in selected_weeks))
        for key, variable in artifacts.activity_night.items():
            apply_value(variable, int(key in selected_nights))
        for key, variable in artifacts.eclo_week.items():
            apply_value(variable, int(key in selected_eclo_weeks))

        occupancy = {
            (assignment.activity_id, assignment.location_id, assignment.week): assignment.co_share_group
            for assignment in schedule.occupancy_assignments
            if (assignment.activity_id, assignment.week) in selected_weeks
        }
        labels_by_location_week: dict[tuple[str, int], set[str]] = defaultdict(set)
        for (_activity_id, location_id, week), label in occupancy.items():
            labels_by_location_week[(location_id, week)].add(label)
        label_index: dict[tuple[str, int, str], int] = {}
        for (location_id, week), labels in labels_by_location_week.items():
            for fallback, label in enumerate(sorted(labels)):
                # Labels are arbitrary in the public contract. Remap the
                # surviving incumbent groups densely so trimming redundant
                # accesses cannot leave holes that conflict with the model's
                # group-prefix symmetry break.
                label_index[(location_id, week, label)] = fallback
        for (activity_id, location_id, week, group), variable in artifacts.group_assignments.items():
            label = occupancy.get((activity_id, location_id, week))
            if label is None:
                continue
            expected_group = label_index.get((location_id, week, label))
            group_count = artifacts.prepared.supply[location_id] + artifacts.policy.supply_excess_allowance
            if expected_group is not None and expected_group < group_count:
                apply_value(variable, int(group == expected_group))

        # Reconstruct a deterministic hidden-night colouring from the same
        # common-base graph used by local preflight. This fills the most
        # important state omitted from the public CSVs and makes the incumbent
        # substantially more useful to CP-SAT.
        activities_by_week: dict[int, list[str]] = defaultdict(list)
        groups_by_activity_week: dict[tuple[str, int], dict[str, str]] = defaultdict(dict)
        for (activity_id, location_id, week), label in occupancy.items():
            groups_by_activity_week[(activity_id, week)][location_id] = label
        for activity_id, week in selected_weeks:
            activities_by_week[week].append(activity_id)
        colour_count = max(
            (
                capacity + artifacts.policy.supply_excess_allowance
                for capacity in artifacts.prepared.supply.values()
            ),
            default=1,
        )
        for week, activity_ids in activities_by_week.items() if not fix else ():
            nodes = sorted(set(activity_ids))
            neighbours: dict[str, set[str]] = {activity_id: set() for activity_id in nodes}
            for left_index, left_id in enumerate(nodes):
                left = artifacts.prepared.activities_by_id[left_id]
                left_groups = groups_by_activity_week[(left_id, week)]
                for right_id in nodes[left_index + 1 :]:
                    right = artifacts.prepared.activities_by_id[right_id]
                    common_base = left.base_locations & right.base_locations
                    right_groups = groups_by_activity_week[(right_id, week)]
                    same_group = any(
                        left_groups.get(location_id) == right_groups.get(location_id)
                        for location_id in common_base
                    )
                    if common_base and not same_group:
                        neighbours[left_id].add(right_id)
                        neighbours[right_id].add(left_id)

            colours: dict[str, int] = {}
            while len(colours) < len(nodes):
                uncoloured = [activity_id for activity_id in nodes if activity_id not in colours]
                activity_id = max(
                    uncoloured,
                    key=lambda item: (
                        len({colours[other] for other in neighbours[item] if other in colours}),
                        len(neighbours[item]),
                        item,
                    ),
                )
                unavailable = {colours[other] for other in neighbours[activity_id] if other in colours}
                colour = next((value for value in range(colour_count) if value not in unavailable), None)
                if colour is None:
                    colours = {}
                    break
                colours[activity_id] = colour
            for activity_id, colour in colours.items():
                variable = artifacts.physical_night.get((activity_id, week))
                if variable is not None:
                    artifacts.model.AddHint(variable, colour)

        weeks_by_activity: dict[str, list[int]] = defaultdict(list)
        for activity_id, week in selected_weeks:
            weeks_by_activity[activity_id].append(week)
        for activity_id, weeks in weeks_by_activity.items():
            if activity_id not in artifacts.first_week:
                continue
            apply_value(artifacts.first_week[activity_id], min(weeks))
            apply_value(artifacts.last_week[activity_id], max(weeks))

    def _build_model(self, prepared: PreparedInstance, policy: ScenarioPolicy) -> _ScenarioCArtifacts:
        model = cp_model.CpModel()
        horizon = prepared.calendar.horizon_weeks
        activities = prepared.activities

        assignments: dict[tuple[str, int, int, int], Any] = {}
        activity_week: dict[tuple[str, int], Any] = {}
        activity_night: dict[tuple[str, int, int], Any] = {}
        eclo_week: dict[tuple[str, int], Any] = {}
        physical_night: dict[tuple[str, int], Any] = {}
        group_assignments: dict[tuple[str, str, int, int], Any] = {}
        eclo_states_all: list[Any] = []
        objective_terms: list[Any] = []
        standard_yield = 10
        eclo_yield = policy.eclo_yield
        group_allowance = policy.supply_excess_allowance if policy.allow_supply_excess else 0

        # Each activity can use at most one access-night in a week.  A standard
        # access yields two half-units; ECLO yields three half-units.
        for item in activities:
            activity_id = item.activity.activity_id
            max_night = item.project.number_of_maximum_access_per_week
            all_states: list[Any] = []
            eclo_states: list[Any] = []
            for week in item.candidate_weeks:
                week_var = model.NewBoolVar(f"access_{activity_id}_w{week}")
                activity_week[(activity_id, week)] = week_var
                night_flags: list[Any] = []
                week_eclo_states: list[Any] = []
                for night in range(1, max_night + 1):
                    standard = model.NewBoolVar(f"access_{activity_id}_w{week}_n{night}_std")
                    eclo = model.NewBoolVar(f"access_{activity_id}_w{week}_n{night}_eclo")
                    model.Add(standard + eclo <= 1)
                    assignments[(activity_id, week, night, 0)] = standard
                    assignments[(activity_id, week, night, 1)] = eclo
                    all_states.extend((standard, eclo))
                    eclo_states_all.append(eclo)
                    eclo_states.append(eclo)
                    week_eclo_states.append(eclo)
                    night_flag = model.NewBoolVar(f"access_{activity_id}_w{week}_n{night}")
                    model.Add(standard + eclo == night_flag)
                    activity_night[(activity_id, week, night)] = night_flag
                    night_flags.append(night_flag)
                model.Add(_sum(night_flags) == week_var)
                week_eclo = model.NewBoolVar(f"eclo_{activity_id}_w{week}")
                model.Add(week_eclo == _sum(week_eclo_states))
                eclo_week[(activity_id, week)] = week_eclo
            delivered_yield = (
                standard_yield * _sum(all_states)
                + (eclo_yield - standard_yield) * _sum(eclo_states)
            )
            required_yield = standard_yield * item.activity.total_accesses
            model.Add(delivered_yield >= required_yield)
            # Do not schedule gratuitous nights. With 1.0/1.5 yields, the
            # minimum feasible delivery is exact or exceeds the requirement
            # by only 0.5 work unit.
            model.Add(delivered_yield <= required_yield + (eclo_yield - standard_yield))

        # Workfront limits apply to distinct activities using one local access
        # night of a contract/type/week, regardless of ECLO state.
        by_contract_type_week: dict[tuple[str, str, int], list[PreparedActivity]] = defaultdict(list)
        for item in activities:
            for week in item.candidate_weeks:
                by_contract_type_week[(item.activity.contract_number, item.activity.activity_type, week)].append(item)
        for (contract, activity_type, week), members in sorted(by_contract_type_week.items()):
            project = prepared.projects[contract]
            for night in range(1, project.number_of_maximum_access_per_week + 1):
                flags = [activity_night[(item.activity.activity_id, week, night)] for item in members]
                model.Add(_sum(flags) <= project.number_of_workfronts)

        # The published access_night is deliberately contract/type-local.
        # Hidden physical nights are compact integer colours used only for the
        # common-base ordering that local preflight can reconstruct. This is
        # equivalent to the former one-hot slot representation but removes a
        # large amount of Boolean symmetry from Scenario C.
        physical_night_count = max(
            (capacity + group_allowance for capacity in prepared.supply.values()),
            default=1,
        )
        for item in activities:
            activity_id = item.activity.activity_id
            for week in item.candidate_weeks:
                physical_night[(activity_id, week)] = model.NewIntVar(
                    0,
                    physical_night_count - 1,
                    f"physical_night_{activity_id}_w{week}",
                )

        # Scenario C permits one additional possession group per location-week.
        for item in activities:
            activity_id = item.activity.activity_id
            for location_id in sorted(item.closure_locations):
                capacity = prepared.supply[location_id]
                group_count = capacity + group_allowance
                for week in item.candidate_weeks:
                    group_variables: list[Any] = []
                    for group in range(group_count):
                        variable = model.NewBoolVar(f"group_{activity_id}_{location_id}_w{week}_g{group}")
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

        # Canonicalise internal possession-group labels. co_share_group is an
        # arbitrary label, so if group 3 is used, groups 1/2 can be used first
        # without changing the schedule's meaning.
        group_used: dict[tuple[str, int, int], Any] = {}
        for location_id, members in sorted(members_by_location.items()):
            capacity = prepared.supply[location_id]
            group_count = capacity + group_allowance
            for week in range(1, horizon + 1):
                group_members = [item for item in members if week in item.candidate_weeks]
                for group in range(group_count):
                    flags = [
                        group_assignments[(item.activity.activity_id, location_id, week, group)]
                        for item in group_members
                    ]
                    used = model.NewBoolVar(f"group_used_{location_id}_w{week}_g{group}")
                    group_used[(location_id, week, group)] = used
                    for flag in flags:
                        model.Add(flag <= used)
                    model.Add(used <= _sum(flags))
                    if group:
                        model.Add(used <= group_used[(location_id, week, group - 1)])

        # Enforce legal PM/PC/C mixes in every internal possession group and
        # price only visible base-location groups above nominal supply, matching
        # the published local score calculation.
        for location_id, members in sorted(members_by_location.items()):
            capacity = prepared.supply[location_id]
            group_count = capacity + group_allowance
            for week in range(1, horizon + 1):
                group_members = [item for item in members if week in item.candidate_weeks]
                visible_members = [
                    item for item in group_members if location_id in item.base_locations
                ]
                visible_group_used: list[Any] = []
                for group in range(group_count):
                    pm_count = _sum([
                        group_assignments[(item.activity.activity_id, location_id, week, group)]
                        for item in group_members if item.project.access_type.value == "PM"
                    ])
                    pc_count = _sum([
                        group_assignments[(item.activity.activity_id, location_id, week, group)]
                        for item in group_members if item.project.access_type.value == "PC"
                    ])
                    c_count = _sum([
                        group_assignments[(item.activity.activity_id, location_id, week, group)]
                        for item in group_members if item.project.access_type.value == "C"
                    ])
                    model.Add(pm_count <= 1)
                    model.Add(pc_count <= 1)
                    model.Add(c_count <= 4)
                    model.Add(4 * pm_count + pc_count + c_count <= 4)

                    visible_flags = [
                        group_assignments[(item.activity.activity_id, location_id, week, group)]
                        for item in visible_members
                    ]
                    visible_used = model.NewBoolVar(
                        f"visible_group_used_{location_id}_w{week}_g{group}"
                    )
                    for flag in visible_flags:
                        model.Add(flag <= visible_used)
                    model.Add(visible_used <= _sum(visible_flags))
                    visible_group_used.append(visible_used)

                # Published excess is the number of visible possession groups
                # above nominal supply, independent of internal group labels.
                # Buffer-only groups may consume a low internal index without
                # creating a scored excess in SCHEDULE_OCCUPANCY.csv.
                extra_used = model.NewBoolVar(f"extra_{location_id}_w{week}")
                visible_count = _sum(visible_group_used)
                model.Add(visible_count <= capacity).OnlyEnforceIf(extra_used.Not())
                model.Add(visible_count >= capacity + 1).OnlyEnforceIf(extra_used)
                objective_terms.append(70 * extra_used)

        # A common base possession permits legal co-sharing across all common
        # closure locations.  Otherwise, incompatible activities cannot use the
        # same internal closure group.
        for left_index, left in enumerate(activities):
            left_id = left.activity.activity_id
            for right in activities[left_index + 1:]:
                right_id = right.activity.activity_id
                common_base = left.base_locations & right.base_locations
                shared_types = {left.project.access_type.value, right.project.access_type.value}
                can_share = shared_types in ({"C"}, {"C", "PC"})
                common_closure = left.closure_locations & right.closure_locations
                directional_conflicts = (
                    (left.base_locations & right.closure_locations)
                    | (right.base_locations & left.closure_locations)
                )
                if not common_closure:
                    continue
                for week in sorted(set(left.candidate_weeks) & set(right.candidate_weeks)):
                    left_week = activity_week[(left_id, week)]
                    right_week = activity_week[(right_id, week)]
                    same_possession = model.NewBoolVar(f"same_possession_{left_id}_{right_id}_w{week}")
                    model.Add(same_possession <= left_week)
                    model.Add(same_possession <= right_week)
                    same_base_flags: list[Any] = []
                    same_base_by_location: dict[str, Any] = {}
                    if can_share:
                        for location_id in sorted(common_base):
                            group_count = prepared.supply[location_id] + group_allowance
                            location_same_flags: list[Any] = []
                            for group in range(group_count):
                                left_group = group_assignments[(left_id, location_id, week, group)]
                                right_group = group_assignments[(right_id, location_id, week, group)]
                                same_base = model.NewBoolVar(
                                    f"same_base_{left_id}_{right_id}_{location_id}_w{week}_g{group}"
                                )
                                model.Add(same_base <= left_group)
                                model.Add(same_base <= right_group)
                                model.Add(same_base >= left_group + right_group - 1)
                                same_base_flags.append(same_base)
                                location_same_flags.append(same_base)
                            same_location = model.NewBoolVar(
                                f"same_base_{left_id}_{right_id}_{location_id}_w{week}"
                            )
                            same_base_by_location[location_id] = same_location
                            for flag in location_same_flags:
                                model.Add(same_location >= flag)
                            model.Add(same_location <= _sum(location_same_flags))
                    else:
                        for location_id in sorted(common_base):
                            same_base_by_location[location_id] = model.NewBoolVar(
                                f"same_base_{left_id}_{right_id}_{location_id}_w{week}"
                            )
                            model.Add(same_base_by_location[location_id] == 0)
                    for flag in same_base_flags:
                        model.Add(same_possession >= flag)
                    model.Add(same_possession <= _sum(same_base_flags))

                    # access_night is local to a contract/type/week. When
                    # two activities from that same contract/type occupy one
                    # submitted possession group at a common base location,
                    # they must use the same local night index as well.
                    if (
                        left.activity.contract_number == right.activity.contract_number
                        and left.activity.activity_type == right.activity.activity_type
                    ):
                        for night in range(1, left.project.number_of_maximum_access_per_week + 1):
                            model.Add(
                                activity_night[(left_id, week, night)]
                                == activity_night[(right_id, week, night)]
                            ).OnlyEnforceIf(same_possession)

                    # A co-share exemption is location-specific. Sharing one
                    # base location does not exempt a second base-vs-buffer
                    # collision elsewhere in the route footprint. Different
                    # possessions may still use separate hidden nights in the
                    # same week, so this is a colour inequality rather than a
                    # forced week separation.
                    for location_id in sorted(directional_conflicts):
                        same_location = same_base_by_location.get(location_id)
                        if same_location is None:
                            model.Add(
                                physical_night[(left_id, week)]
                                != physical_night[(right_id, week)]
                            ).OnlyEnforceIf([left_week, right_week])

                    # Separate common-base possession groups must use
                    # different hidden physical-night colours. Same-group
                    # members are one possession and use the same colour.
                    for location_id, same_location in same_base_by_location.items():
                        model.Add(
                            physical_night[(left_id, week)]
                            == physical_night[(right_id, week)]
                        ).OnlyEnforceIf(same_location)
                        model.Add(
                            physical_night[(left_id, week)]
                            != physical_night[(right_id, week)]
                        ).OnlyEnforceIf(
                            [left_week, right_week, same_location.Not()]
                        )

                    for location_id in sorted(common_closure):
                        group_count = prepared.supply[location_id] + group_allowance
                        for group in range(group_count):
                            left_group = group_assignments[(left_id, location_id, week, group)]
                            right_group = group_assignments[(right_id, location_id, week, group)]
                            model.Add(left_group + right_group <= 1 + same_possession)

        # Scenario C ECLO accesses affecting each line must fit one continuous
        # window of at most two calendar weeks.  A cross-line Live footprint
        # participates in both line windows automatically.
        eclo_by_line: dict[str, list[tuple[int, Any]]] = defaultdict(list)
        for item in activities:
            affected_lines = {location.split(":")[1] for location in item.closure_locations}
            for week in item.candidate_weeks:
                for line in affected_lines:
                    eclo_by_line[line].append((week, eclo_week[(item.activity.activity_id, week)]))
        for line, candidates in sorted(eclo_by_line.items()):
            starts = {
                start: model.NewBoolVar(f"eclo_window_{line}_start_{start}")
                for start in range(1, horizon + 1)
            }
            model.Add(_sum(list(starts.values())) <= 1)
            for week, eclo_var in candidates:
                coverage = [
                    variable for start, variable in starts.items()
                    if start <= week <= start + policy.eclo_window_weeks - 1
                ]
                model.Add(eclo_var <= _sum(coverage))

        first_week: dict[str, Any] = {}
        last_week: dict[str, Any] = {}
        scaled_contract_weight = {1: 1000, 2: 100, 3: 10}
        scaled_activity_nudge = {1: 3, 2: 2, 3: 0}
        for item in activities:
            activity_id = item.activity.activity_id
            first_values: list[Any] = []
            last_values: list[Any] = []
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
                overrun_table.append(max(0, (prepared.calendar.week_end(week) - item.project.planned_completion_date).days))
            overrun = model.NewIntVar(0, max(overrun_table), f"overrun_{activity_id}")
            model.AddElement(last, overrun_table, overrun)
            base_weight = scaled_contract_weight[item.project.contract_priority]
            nudge = scaled_activity_nudge[item.activity.activity_priority]
            objective_terms.append((base_weight + base_weight * nudge // 10) * overrun)

        for item in activities:
            predecessor = item.activity.predecessor_activity_id
            if predecessor:
                model.Add(last_week[predecessor] + 1 <= first_week[item.activity.activity_id])

        objective_terms.append(50 * _sum(eclo_states_all))
        model.Minimize(_sum(objective_terms))
        return _ScenarioCArtifacts(
            model=model,
            prepared=prepared,
            policy=policy,
            assignments=assignments,
            activity_week=activity_week,
            activity_night=activity_night,
            eclo_week=eclo_week,
            physical_night=physical_night,
            group_assignments=group_assignments,
            first_week=first_week,
            last_week=last_week,
        )

    def _extract_schedule(self, artifacts: _ScenarioCArtifacts, solver: Any) -> ScenarioSchedule:
        prepared = artifacts.prepared
        access_assignments: list[AccessAssignment] = []
        occupancy_assignments: list[OccupancyAssignment] = []
        selected_weeks_by_activity: dict[str, list[int]] = {}

        for item in prepared.activities:
            activity_id = item.activity.activity_id
            selected: list[tuple[int, int, int]] = []
            for week in item.candidate_weeks:
                for night in range(1, item.project.number_of_maximum_access_per_week + 1):
                    for eclo in (0, 1):
                        variable = artifacts.assignments[(activity_id, week, night, eclo)]
                        if solver.Value(variable):
                            selected.append((week, night, eclo))
            selected.sort()
            if 2 * len(selected) + sum(eclo for _week, _night, eclo in selected) < 2 * item.activity.total_accesses:
                raise SolverError(f"internal extraction error: {activity_id} does not meet workload.")
            selected_weeks_by_activity[activity_id] = [week for week, _night, _eclo in selected]
            for access_seq, (week, night, eclo) in enumerate(selected, start=1):
                access_assignments.append(
                    AccessAssignment(
                        activity_id=activity_id,
                        access_seq=access_seq,
                        week=week,
                        eclo=eclo,
                        access_night=night,
                    )
                )
                for location_id in sorted(item.base_locations):
                    group_count = prepared.supply[location_id] + (
                        artifacts.policy.supply_excess_allowance
                        if artifacts.policy.allow_supply_excess
                        else 0
                    )
                    selected_group = next(
                        (
                            group for group in range(group_count)
                            if solver.Value(artifacts.group_assignments[(activity_id, location_id, week, group)])
                        ),
                        None,
                    )
                    if selected_group is None:
                        raise SolverError(
                            f"internal extraction error: no possession group for {activity_id}, {location_id}, {week}."
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
            completion_by_contract[item.activity.contract_number] = max(
                completion,
                completion_by_contract.get(item.activity.contract_number, completion),
            )

        contract_results: list[ContractResult] = []
        for project in sorted(prepared.projects.values(), key=lambda item: item.contract_number):
            completion = completion_by_contract.get(project.contract_number)
            if completion is None:
                raise SolverError(f"contract {project.contract_number} has no activities and cannot produce RESULTS.csv.")
            contract_results.append(
                ContractResult(
                    scenario=Scenario.C,
                    contract_number=project.contract_number,
                    simulated_completion_date=completion,
                    overrun_days=max(0, (completion - project.planned_completion_date).days),
                )
            )

        access_assignments.sort(key=lambda item: (item.activity_id, item.access_seq))
        occupancy_assignments.sort(key=lambda item: (item.activity_id, item.week, item.location_id))
        return ScenarioSchedule(
            scenario=Scenario.C,
            access_assignments=access_assignments,
            occupancy_assignments=occupancy_assignments,
            contract_results=contract_results,
        )
