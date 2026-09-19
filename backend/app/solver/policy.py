"""Scenario policies for the CP-SAT scheduling models."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.models import Scenario


class UnsupportedScenarioError(ValueError):
    """Raised when a scenario has not yet been implemented."""


@dataclass(frozen=True)
class ScenarioPolicy:
    scenario: Scenario
    allow_eclo: bool
    allow_supply_excess: bool
    supply_excess_allowance: int
    planned_completion_hard: bool
    objective_name: str
    objective_scale: int = 10
    eclo_window_weeks: int | None = None

    @property
    def eclo_yield(self) -> int:
        """Return the integer workload yield used by the model."""

        return 15 if self.allow_eclo else 10


SCENARIO_A_POLICY = ScenarioPolicy(
    scenario=Scenario.A,
    allow_eclo=False,
    allow_supply_excess=False,
    supply_excess_allowance=0,
    planned_completion_hard=False,
    objective_name="priority_weighted_planned_completion_overrun",
)


SCENARIO_C_POLICY = ScenarioPolicy(
    scenario=Scenario.C,
    allow_eclo=True,
    allow_supply_excess=True,
    supply_excess_allowance=1,
    planned_completion_hard=False,
    objective_name="priority_weighted_overrun_plus_excess_and_eclo",
    eclo_window_weeks=2,
)


def policy_for(scenario: Scenario) -> ScenarioPolicy:
    """Return the central policy object for a supported scenario.

    Scenario B deliberately fails loudly until its scenario-specific rules and
    objective are implemented; it must not silently receive A or C's policy.
    """

    if scenario is Scenario.A:
        return SCENARIO_A_POLICY
    if scenario is Scenario.C:
        return SCENARIO_C_POLICY
    raise UnsupportedScenarioError(
        f"Scenario {scenario.value} is not implemented yet; Scenario A and Scenario C are available."
    )
