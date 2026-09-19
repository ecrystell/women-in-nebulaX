"""Adapter from the API's InputInstance contract to the Scenario A/C solvers."""

from __future__ import annotations

from ..api.schemas import ScenarioChange
from ..api.solver_contract import ScenarioUnavailable, SolverInputInvalid
from ..domain.models import Scenario
from ..domain.preprocessing import PreparedInstance, PreparationError
from .cp_sat import ScenarioASolver, SolveResult
from .policy import UnsupportedScenarioError
from .scenario_c import ScenarioCSolver


class CpSatSolverAdapter:
    """Implement the existing RunService solver protocol for Scenario A/C."""

    def __init__(self, *, time_limit_seconds: float = 60.0) -> None:
        self.solvers = {
            Scenario.A: ScenarioASolver(time_limit_seconds=time_limit_seconds),
            Scenario.C: ScenarioCSolver(time_limit_seconds=time_limit_seconds),
        }
        self.last_result: SolveResult | None = None

    def solve(
        self,
        prepared_instance: PreparedInstance,
        scenario: Scenario,
        scenario_change: ScenarioChange | None = None,
    ):
        try:
            solver = self.solvers.get(scenario)
            if solver is None:
                raise UnsupportedScenarioError(
                    f"Scenario {scenario.value} is not implemented by the CP-SAT adapter."
                )
            result = solver.solve_prepared_with_diagnostics(prepared_instance, scenario, scenario_change)
        except UnsupportedScenarioError as error:
            raise ScenarioUnavailable(str(error)) from error
        except PreparationError as error:
            raise SolverInputInvalid(str(error)) from error
        self.last_result = result
        # Importing this small API dataclass here avoids coupling the core
        # solver's canonical result to the service's orchestration wrapper.
        from ..api.run_service import SolverOutput

        return SolverOutput(schedule=result.schedule)
