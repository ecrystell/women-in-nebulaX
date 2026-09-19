"""Published score helpers independent from CP-SAT extraction."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from ..domain.models import InstanceBundle, ScenarioSchedule
from ..domain.preprocessing import PlanningCalendar, require_prepared


CONTRACT_WEIGHT = {1: 100, 2: 10, 3: 1}
ACTIVITY_PRIORITY_NUDGE = {1: 0.3, 2: 0.2, 3: 0.0}


def planning_calendar(instance: InstanceBundle) -> PlanningCalendar:
    return require_prepared(instance).calendar


def activity_completion_dates(
    instance: InstanceBundle, schedule: ScenarioSchedule, *, calendar: PlanningCalendar | None = None
) -> dict[str, date]:
    calendar = calendar or planning_calendar(instance)
    last_week: dict[str, int] = defaultdict(int)
    for assignment in schedule.access_assignments:
        last_week[assignment.activity_id] = max(last_week[assignment.activity_id], assignment.week)
    return {
        activity_id: calendar.week_end(week)
        for activity_id, week in last_week.items()
    }


def priority_weighted_overrun(
    instance: InstanceBundle, schedule: ScenarioSchedule, *, calendar: PlanningCalendar | None = None
) -> float:
    projects = {project.contract_number: project for project in instance.projects}
    activities = {activity.activity_id: activity for activity in instance.activities}
    completion = activity_completion_dates(instance, schedule, calendar=calendar)
    completion_by_contract: dict[str, date] = {}
    for activity_id, completed in completion.items():
        contract = activities[activity_id].contract_number
        completion_by_contract[contract] = max(
            completed, completion_by_contract.get(contract, completed)
        )
    score = 0.0
    for activity in instance.activities:
        project = projects[activity.contract_number]
        completed = completion_by_contract.get(activity.contract_number)
        if completed is None:
            continue
        overrun_days = max(0, (completed - project.planned_completion_date).days)
        score += (
            CONTRACT_WEIGHT[project.contract_priority]
            * (1 + ACTIVITY_PRIORITY_NUDGE[activity.activity_priority])
            * overrun_days
        )
    return score


def scenario_a_score(
    instance: InstanceBundle, schedule: ScenarioSchedule, *, calendar: PlanningCalendar | None = None
) -> float:
    """Return the published Scenario A score; no ECLO/excess terms exist in A."""

    return priority_weighted_overrun(instance, schedule, calendar=calendar)


def excess_access_nights(instance: InstanceBundle, schedule: ScenarioSchedule) -> int:
    """Count visible possession groups above nominal location supply."""

    prepared = require_prepared(instance)
    groups_by_location_week: set[tuple[str, int, str]] = {
        (assignment.location_id, assignment.week, assignment.co_share_group)
        for assignment in schedule.occupancy_assignments
    }
    counts: defaultdict[tuple[str, int], int] = defaultdict(int)
    for location_id, week, _group in groups_by_location_week:
        counts[(location_id, week)] += 1
    return sum(
        max(0, count - prepared.supply[location_id])
        for (location_id, _week), count in counts.items()
        if location_id in prepared.supply
    )


def scenario_c_score(
    instance: InstanceBundle, schedule: ScenarioSchedule, *, calendar: PlanningCalendar | None = None
) -> float:
    """Return Scenario C's exact combined penalty score."""

    eclo_nights = sum(1 for assignment in schedule.access_assignments if assignment.eclo)
    return (
        priority_weighted_overrun(instance, schedule, calendar=calendar)
        + 7 * excess_access_nights(instance, schedule)
        + 5 * eclo_nights
    )
