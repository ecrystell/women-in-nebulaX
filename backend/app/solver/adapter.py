"""Adapter from the API's InputInstance contract to the Scenario A solver."""

from __future__ import annotations

from ..api.schemas import InputInstance, ScenarioChange
from ..domain.models import Scenario
from .cp_sat import ScenarioASolver, SolveResult


class CpSatSolverAdapter:
    """Implement the existing RunService solver protocol for Scenario A."""

    def __init__(self, *, time_limit_seconds: float = 60.0) -> None:
        self.solver = ScenarioASolver(time_limit_seconds=time_limit_seconds)
        self.last_result: SolveResult | None = None

    def solve(
        self,
        input_instance: InputInstance,
        scenario: Scenario,
        scenario_change: ScenarioChange | None = None,
    ):
        result = self.solver.solve_with_diagnostics(
            input_instance.to_bundle(), scenario, scenario_change
        )
        self.last_result = result
        # Importing this small API dataclass here avoids coupling the core
        # solver's canonical result to the service's orchestration wrapper.
        from ..api.run_service import SolverOutput

        return SolverOutput(schedule=result.schedule)
