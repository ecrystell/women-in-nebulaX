"""API adapter for the authoritative A/B/C CP-SAT scheduling model."""

from __future__ import annotations

from app.api.schemas import ScenarioChange, SolverDiagnostics
from app.api.solver_contract import ScenarioUnavailable, SolverInputInvalid, SolverTimedOut
from app.domain.models import Scenario, ScenarioSchedule
from app.domain.preprocessing import PreparedInstance, PreparationError
from app.validation.preflight import validate_schedule

from .cp_sat import CpSatRailSolver, SolveError, SolverConfig

API_SOLVE_TIME_LIMIT_SECONDS = 150.0


class CpSatSolverAdapter:
    """Expose the delivered A/B/C model through ``RunService`` safely."""

    supported_scenarios = (Scenario.A, Scenario.B, Scenario.C)
    recovery_scenarios = (Scenario.C,)
    supports_recovery = True

    def __init__(self, *, time_limit_seconds: float = API_SOLVE_TIME_LIMIT_SECONDS) -> None:
        if time_limit_seconds <= 0 or time_limit_seconds > API_SOLVE_TIME_LIMIT_SECONDS:
            raise ValueError(
                "API solver time limit must be greater than 0 and at most "
                f"{API_SOLVE_TIME_LIMIT_SECONDS:.0f} seconds"
            )
        self.time_limit_seconds = time_limit_seconds
        self.last_diagnostics: SolverDiagnostics | None = None

    def _new_solver(self) -> CpSatRailSolver:
        return CpSatRailSolver(SolverConfig(max_time_seconds=self.time_limit_seconds))

    def _diagnostics(
        self, solver: CpSatRailSolver, *, recovery_source: str | None = None
    ) -> SolverDiagnostics:
        return SolverDiagnostics(
            status=solver.last_status or "UNKNOWN",
            wall_time_seconds=float(solver.last_wall_time_seconds or 0.0),
            time_limit_seconds=self.time_limit_seconds,
            recovery_source=recovery_source,
        )

    @staticmethod
    def _overrides(change: ScenarioChange | None) -> dict[tuple[str, int], int]:
        return {
            (override.location_id, override.week): override.supply_capacity
            for override in (change.supply_overrides if change else [])
        }

    @staticmethod
    def _score(report) -> float:
        value = report.soft_scores.get("objective_score")
        if value is None:
            raise RuntimeError("local preflight did not calculate an objective score")
        return float(value)

    def solve(
        self,
        prepared_instance: PreparedInstance,
        scenario: Scenario,
        scenario_change: ScenarioChange | None = None,
        baseline_schedule: ScenarioSchedule | None = None,
    ):
        self.last_diagnostics = None
        if scenario not in self.supported_scenarios:
            raise ScenarioUnavailable(f"Scenario {scenario.value} is not implemented by the active solver.")
        if scenario_change is not None:
            return self._solve_recovery(prepared_instance, scenario, scenario_change, baseline_schedule)
        return self._solve_fresh(prepared_instance, scenario)

    def _solve_fresh(self, prepared: PreparedInstance, scenario: Scenario):
        solver = self._new_solver()
        try:
            schedule = solver.solve_prepared(prepared, scenario)
        except PreparationError as error:
            raise SolverInputInvalid(str(error)) from error
        except SolveError as error:
            self.last_diagnostics = self._diagnostics(solver)
            if self.last_diagnostics.status == "UNKNOWN":
                raise SolverTimedOut(
                    f"Scenario {scenario.value} did not find a candidate within {self.time_limit_seconds:.0f} seconds."
                ) from error
            raise RuntimeError(str(error)) from error

        diagnostics = self._diagnostics(solver)
        if diagnostics.status not in {"FEASIBLE", "OPTIMAL"}:
            self.last_diagnostics = diagnostics
            raise SolverTimedOut(
                f"Scenario {scenario.value} did not return a FEASIBLE or OPTIMAL candidate."
            )
        self.last_diagnostics = diagnostics
        from app.api.run_service import SolverOutput

        return SolverOutput(schedule=schedule, diagnostics=diagnostics)

    def _solve_recovery(
        self,
        prepared: PreparedInstance,
        scenario: Scenario,
        change: ScenarioChange,
        baseline: ScenarioSchedule | None,
    ):
        if scenario not in self.recovery_scenarios:
            raise ScenarioUnavailable(
                f"Recovery optimisation is currently available only for Scenario C, not Scenario {scenario.value}."
            )
        if baseline is None:
            raise SolverInputInvalid("Recovery requires the referenced baseline schedule.")

        overrides = self._overrides(change)
        baseline_report = validate_schedule(prepared, baseline, overrides)
        baseline_valid = not baseline_report.hard_violations
        baseline_score = self._score(baseline_report) if baseline_valid else None
        solver = self._new_solver()
        candidate: ScenarioSchedule | None = None
        solve_error: SolveError | None = None
        try:
            candidate = solver.solve_prepared(prepared, scenario, change, baseline=baseline)
            candidate_report = validate_schedule(prepared, candidate, overrides)
            if candidate_report.hard_violations:
                raise RuntimeError("The recovery candidate failed local preflight against the changed supply.")
        except SolveError as error:
            solve_error = error

        if candidate is None:
            if not baseline_valid:
                self.last_diagnostics = self._diagnostics(solver)
                if self.last_diagnostics.status == "UNKNOWN":
                    raise SolverTimedOut(
                        "Recovery timed out and the baseline is not valid for the requested disruption."
                    ) from solve_error
                raise RuntimeError(
                    "Recovery produced no candidate and the baseline is not valid for the requested disruption."
                ) from solve_error
            diagnostics = self._diagnostics(solver, recovery_source="incumbent_fallback")
            selected = baseline
        else:
            candidate_score = self._score(candidate_report)
            if baseline_score is not None and baseline_score <= candidate_score:
                diagnostics = self._diagnostics(solver, recovery_source="incumbent_not_worse")
                selected = baseline
            else:
                diagnostics = self._diagnostics(solver, recovery_source="reoptimized")
                selected = candidate
        self.last_diagnostics = diagnostics
        from app.api.run_service import SolverOutput

        return SolverOutput(schedule=selected, diagnostics=diagnostics)
