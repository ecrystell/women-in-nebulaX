"""Adapter from the API's InputInstance contract to the Scenario A solver."""

from __future__ import annotations

from ..api.schemas import ScenarioChange
from ..api.solver_contract import ScenarioUnavailable, SolverInputInvalid
from ..domain.models import Scenario
from ..domain.preprocessing import PreparedInstance, PreparationError
from .cp_sat import ScenarioASolver, SolveResult
from .policy import UnsupportedScenarioError


class CpSatSolverAdapter:
    """Implement the existing RunService solver protocol for Scenario A."""

    def __init__(self, *, time_limit_seconds: float = 60.0) -> None:
        self.solver = ScenarioASolver(time_limit_seconds=time_limit_seconds)
        self.last_result: SolveResult | None = None

    def solve(
        self,
        prepared_instance: PreparedInstance,
        scenario: Scenario,
        scenario_change: ScenarioChange | None = None,
    ):
        try:
            result = self.solver.solve_prepared_with_diagnostics(prepared_instance, scenario, scenario_change)
        except UnsupportedScenarioError as error:
            raise ScenarioUnavailable(str(error)) from error
        except PreparationError as error:
            raise SolverInputInvalid(str(error)) from error
        self.last_result = result
        # Importing this small API dataclass here avoids coupling the core
        # solver's canonical result to the service's orchestration wrapper.
        from ..api.run_service import SolverOutput

        return SolverOutput(schedule=result.schedule)
