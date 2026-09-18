"""Scenario policies for the shared CP-SAT scheduling model.

Only Scenario A is implemented in this workstream.  Keeping the policy in a
single object is intentional: later scenarios should change policy data and
scenario-specific constraints/objectives, not duplicate the scheduling model.
"""

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


def policy_for(scenario: Scenario) -> ScenarioPolicy:
    """Return the central policy object for a supported scenario.

    B and C deliberately fail loudly until their scenario-specific rules and
    objectives are implemented; they must not silently receive A's policy.
    """

    if scenario is Scenario.A:
        return SCENARIO_A_POLICY
    raise UnsupportedScenarioError(
        f"Scenario {scenario.value} is not implemented yet; only Scenario A is available."
    )
