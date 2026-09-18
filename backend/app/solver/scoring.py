"""Scenario A score helpers independent from CP-SAT extraction."""

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
    score = 0.0
    for activity_id, completed in completion.items():
        activity = activities[activity_id]
        project = projects[activity.contract_number]
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
