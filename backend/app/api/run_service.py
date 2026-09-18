"""Ephemeral run orchestration; solver and validator remain pluggable boundaries."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Protocol
from uuid import uuid4

from app.api.schemas import (
    InputInstance,
    InputInstanceSummary,
    RunProblem,
    RunStatus,
    RunView,
    ScenarioChange,
    Schedule,
    ScheduleDiff,
    ValidationReport,
)
from app.domain.models import Scenario, ScenarioSchedule
from app.exports.csv_writer import write_submission
from app.validation.adapter import OfficialValidatorAdapter
from app.validation.preflight import validate_schedule


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SolverUnavailable(RuntimeError):
    """Raised until Role 3 connects the CP-SAT scheduling authority."""


@dataclass
class SolverOutput:
    schedule: ScenarioSchedule
    schedule_diff: ScheduleDiff | None = None


class SolverAdapter(Protocol):
    def solve(
        self,
        input_instance: InputInstance,
        scenario: Scenario,
        scenario_change: ScenarioChange | None = None,
    ) -> SolverOutput: ...


class UnavailableSolver:
    def solve(
        self,
        input_instance: InputInstance,
        scenario: Scenario,
        scenario_change: ScenarioChange | None = None,
    ) -> SolverOutput:
        raise SolverUnavailable(
            "The CP-SAT solver is not connected yet. This input was parsed but no candidate schedule was created."
        )


@dataclass
class RunRecord:
    run_id: str
    input_instance: InputInstance
    scenario: Scenario
    created_at: datetime
    updated_at: datetime
    recovery_of_run_id: str | None = None
    scenario_change: ScenarioChange | None = None
    status: RunStatus = RunStatus.ACCEPTED
    schedule: Schedule | None = None
    validation_report: ValidationReport | None = None
    schedule_diff: ScheduleDiff | None = None
    problem: RunProblem | None = None
    export_dir: Path | None = None

    def to_view(self) -> RunView:
        return RunView(
            run_id=self.run_id,
            status=self.status,
            scenario=self.scenario,
            input_instance=InputInstanceSummary.from_instance(self.input_instance),
            created_at=self.created_at,
            updated_at=self.updated_at,
            recovery_of_run_id=self.recovery_of_run_id,
            schedule=self.schedule,
            validation_report=self.validation_report,
            schedule_diff=self.schedule_diff,
            problem=self.problem,
        )


class InMemoryRunStore:
    """Process-local state; hidden input disappears on restart or explicit clear()."""

    def __init__(self) -> None:
        self._records: dict[str, RunRecord] = {}
        self._lock = Lock()

    def add(self, record: RunRecord) -> None:
        with self._lock:
            self._records[record.run_id] = record

    def get(self, run_id: str) -> RunRecord | None:
        with self._lock:
            return self._records.get(run_id)

    def clear(self) -> None:
        with self._lock:
            records = list(self._records.values())
            self._records.clear()
        for record in records:
            if record.export_dir:
                shutil.rmtree(record.export_dir, ignore_errors=True)


class RunService:
    def __init__(
        self,
        *,
        solver: SolverAdapter | None = None,
        validator: OfficialValidatorAdapter | None = None,
        store: InMemoryRunStore | None = None,
    ) -> None:
        self.solver = solver or UnavailableSolver()
        self.validator = validator or OfficialValidatorAdapter()
        self.store = store or InMemoryRunStore()

    def create_run(
        self,
        input_instance: InputInstance,
        scenario: Scenario,
        *,
        recovery_of_run_id: str | None = None,
        scenario_change: ScenarioChange | None = None,
    ) -> RunRecord:
        now = utc_now()
        record = RunRecord(
            run_id=str(uuid4()),
            input_instance=input_instance,
            scenario=scenario,
            created_at=now,
            updated_at=now,
            recovery_of_run_id=recovery_of_run_id,
            scenario_change=scenario_change,
            validation_report=ValidationReport.from_domain(self.validator.status()),
        )
        self.store.add(record)
        return record

    def dispatch(self, run_id: str) -> None:
        record = self.store.get(run_id)
        if record is None:
            return
        record.status = RunStatus.RUNNING
        record.updated_at = utc_now()
        try:
            output = self.solver.solve(record.input_instance, record.scenario, record.scenario_change)
        except SolverUnavailable as error:
            record.status = RunStatus.BLOCKED
            record.problem = RunProblem(code="solver_unavailable", message=str(error))
            record.updated_at = utc_now()
            return
        except Exception as error:  # Adapter errors are returned as a safe run failure.
            record.status = RunStatus.FAILED
            record.problem = RunProblem(code="solver_failed", message=str(error))
            record.updated_at = utc_now()
            return

        schedule_id = str(uuid4())
        record.schedule = Schedule.from_domain(
            output.schedule,
            schedule_id=schedule_id,
            input_instance_id=record.input_instance.source.instance_id,
            generated_at=utc_now(),
        )
        record.schedule_diff = output.schedule_diff
        record.validation_report = ValidationReport.from_domain(
            validate_schedule(record.input_instance.to_bundle(), output.schedule), schedule_id=schedule_id
        )
        record.export_dir = Path(tempfile.mkdtemp(prefix="railaccess-run-"))
        write_submission(output.schedule, record.export_dir)
        record.status = RunStatus.SUCCEEDED
        record.updated_at = utc_now()

    def get_view(self, run_id: str) -> RunView | None:
        record = self.store.get(run_id)
        return record.to_view() if record else None

    def get_export(self, run_id: str, filename: str) -> Path | None:
        record = self.store.get(run_id)
        if record is None or record.status != RunStatus.SUCCEEDED or not record.export_dir:
            return None
        path = record.export_dir / filename
        return path if path.is_file() else None

    def create_recovery(self, base_run_id: str, change: ScenarioChange) -> RunRecord | None:
        base = self.store.get(base_run_id)
        if base is None or base.status != RunStatus.SUCCEEDED or base.schedule is None:
            return None
        return self.create_run(
            base.input_instance,
            base.scenario,
            recovery_of_run_id=base_run_id,
            scenario_change=change,
        )
