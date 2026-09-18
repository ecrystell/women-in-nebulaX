"""Ephemeral run orchestration; solver and validator remain pluggable boundaries."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import tempfile
import zipfile
from hmac import compare_digest
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
    OrganiserEvidence,
    OrganiserEvidenceInput,
    ScenarioChange,
    Schedule,
    ScheduleDiff,
    SubmissionManifest,
    SubmissionPackageSummary,
    ValidationReport,
)
from app.ingestion.csv_loader import INPUT_TABLES
from app.domain.models import Scenario, ScenarioSchedule
from app.domain.preprocessing import PreparedInstance, prepare_instance
from app.ai import evidence as evidence_builder
from app.api.schemas import CopilotMode, EvidenceEnvelope
from app.exports.csv_writer import write_submission
from app.validation.adapter import OfficialValidatorAdapter
from app.validation.preflight import preparation_report, validate_schedule
from app.api.solver_contract import ScenarioUnavailable, SolverInputInvalid, SolverUnavailable


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SolverOutput:
    schedule: ScenarioSchedule
    schedule_diff: ScheduleDiff | None = None


class SolverAdapter(Protocol):
    def solve(
        self,
        prepared_instance: PreparedInstance,
        scenario: Scenario,
        scenario_change: ScenarioChange | None = None,
    ) -> SolverOutput: ...


class SubmissionPackageError(ValueError):
    """A package or evidence operation cannot be completed for this run."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class EvidenceUnavailable(ValueError):
    """A run has no candidate schedule from which to build safe evidence."""


@dataclass
class SubmissionPackageRecord:
    manifest: SubmissionManifest
    directory: Path
    bundle_path: Path
    organiser_evidence: OrganiserEvidence | None = None
    evidence_record_path: Path | None = None

    def to_summary(self) -> SubmissionPackageSummary:
        return SubmissionPackageSummary(
            package_id=self.manifest.package_id,
            run_id=self.manifest.run_id,
            schedule_id=self.manifest.schedule_id,
            scenario=self.manifest.scenario,
            created_at=self.manifest.created_at,
            build_commit=self.manifest.build_commit,
            organiser_evidence=self.organiser_evidence,
        )


class UnavailableSolver:
    def solve(
        self,
        prepared_instance: PreparedInstance,
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
    access_token: str = field(repr=False, default="")
    access_token_hash: str = field(repr=False, default="")
    prepared_instance: PreparedInstance | None = field(repr=False, default=None)
    last_accessed_at: datetime | None = None
    copilot_request_times: list[datetime] = field(default_factory=list, repr=False)
    recovery_of_run_id: str | None = None
    scenario_change: ScenarioChange | None = None
    status: RunStatus = RunStatus.ACCEPTED
    schedule: Schedule | None = None
    validation_report: ValidationReport | None = None
    schedule_diff: ScheduleDiff | None = None
    problem: RunProblem | None = None
    export_dir: Path | None = None
    submission_packages: dict[str, SubmissionPackageRecord] = field(default_factory=dict)

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
            submission_packages=[
                package.to_summary()
                for package in sorted(self.submission_packages.values(), key=lambda item: item.manifest.created_at)
            ],
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

    def remove(self, run_id: str) -> None:
        with self._lock:
            record = self._records.pop(run_id, None)
        if record and record.export_dir:
            shutil.rmtree(record.export_dir, ignore_errors=True)

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

    @staticmethod
    def _run_ttl_seconds() -> int:
        raw = os.getenv("RAILACCESS_RUN_TTL_SECONDS", "1800")
        try:
            return max(60, min(int(raw), 86_400))
        except ValueError:
            return 1800

    def create_run(
        self,
        input_instance: InputInstance,
        scenario: Scenario,
        *,
        recovery_of_run_id: str | None = None,
        scenario_change: ScenarioChange | None = None,
    ) -> RunRecord:
        now = utc_now()
        access_token = secrets.token_urlsafe(32)
        record = RunRecord(
            run_id=str(uuid4()),
            input_instance=input_instance,
            scenario=scenario,
            created_at=now,
            updated_at=now,
            access_token=access_token,
            access_token_hash=hashlib.sha256(access_token.encode("utf-8")).hexdigest(),
            last_accessed_at=now,
            recovery_of_run_id=recovery_of_run_id,
            scenario_change=scenario_change,
            validation_report=ValidationReport.from_domain(self.validator.status()),
        )
        self.store.add(record)
        return record

    def authorize(self, run_id: str, token: str | None) -> RunRecord | None:
        """Return the active run only for its issuing browser's opaque cookie."""

        record = self.store.get(run_id)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest() if token else ""
        if record is None or not token or not compare_digest(record.access_token_hash, token_hash):
            return None
        last_access = record.last_accessed_at or record.updated_at
        if (utc_now() - last_access).total_seconds() > self._run_ttl_seconds():
            self.store.remove(run_id)
            return None
        record.last_accessed_at = utc_now()
        return record

    def dispatch(self, run_id: str) -> None:
        record = self.store.get(run_id)
        if record is None:
            return
        record.status = RunStatus.RUNNING
        record.updated_at = utc_now()
        preparation = prepare_instance(record.input_instance.to_bundle())
        if preparation.prepared is None:
            record.validation_report = ValidationReport.from_domain(preparation_report(preparation.findings))
            record.status = RunStatus.FAILED
            record.problem = RunProblem(
                code="solver_input_invalid",
                message="The input failed shared preprocessing validation.",
            )
            record.updated_at = utc_now()
            return
        record.prepared_instance = preparation.prepared
        try:
            output = self.solver.solve(preparation.prepared, record.scenario, record.scenario_change)
        except SolverUnavailable as error:
            record.status = RunStatus.BLOCKED
            record.problem = RunProblem(code="solver_unavailable", message=str(error))
            record.updated_at = utc_now()
            return
        except ScenarioUnavailable as error:
            record.status = RunStatus.BLOCKED
            record.problem = RunProblem(code="scenario_unavailable", message=str(error))
            record.updated_at = utc_now()
            return
        except SolverInputInvalid as error:
            record.status = RunStatus.FAILED
            record.problem = RunProblem(code="solver_input_invalid", message=str(error))
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
            validate_schedule(preparation.prepared, output.schedule), schedule_id=schedule_id
        )

        if record.validation_report.hard_violations:
            record.status = RunStatus.FAILED
            record.problem = RunProblem(
                code="preflight_failed",
                message=(
                    "The solver returned a candidate with local hard-rule violations. "
                    "Inspect the validation report; submission exports are unavailable."
                ),
            )
            record.updated_at = utc_now()
            return

        try:
            record.export_dir = Path(tempfile.mkdtemp(prefix="railaccess-run-"))
            write_submission(output.schedule, record.export_dir)
        except Exception as error:  # pragma: no cover - defensive boundary
            record.status = RunStatus.FAILED
            record.problem = RunProblem(
                code="export_failed",
                message=f"Could not create the submission CSVs: {error}",
            )
            record.export_dir = None
            record.updated_at = utc_now()
            return
        record.status = RunStatus.SUCCEEDED
        record.updated_at = utc_now()

    def get_view(self, run_id: str) -> RunView | None:
        record = self.store.get(run_id)
        return record.to_view() if record else None

    def evidence_for(self, record: RunRecord, mode: CopilotMode, activity_id: str | None = None) -> EvidenceEnvelope:
        if record.schedule is None or record.validation_report is None or record.prepared_instance is None:
            raise EvidenceUnavailable("Evidence requires a candidate schedule and shared preprocessing facts.")
        common = {
            "run_id": record.run_id,
            "schedule_id": record.schedule.schedule_id,
            "scenario": record.scenario,
            "prepared": record.prepared_instance,
            "schedule_placements": record.schedule.placements,
            "report": record.validation_report,
        }
        if mode is CopilotMode.ACTIVITY_EXPLANATION:
            if activity_id is None:
                raise EvidenceUnavailable("An activity explanation requires an activity id.")
            result = evidence_builder.activity_evidence(
                **common,
                contract_results=record.schedule.contract_results,
                activity_id=activity_id,
            )
            if result is None:
                raise EvidenceUnavailable(f"No scheduled activity {activity_id} exists in this run.")
            return result
        if mode is CopilotMode.CAPACITY_HOTSPOTS:
            return evidence_builder.hotspots_evidence(**common)
        return evidence_builder.handover_evidence(
            **common,
            contract_results=record.schedule.contract_results,
        )

    def consume_copilot_request(self, record: RunRecord) -> bool:
        now = utc_now()
        cutoff = now.timestamp() - 60
        record.copilot_request_times = [item for item in record.copilot_request_times if item.timestamp() >= cutoff]
        if len(record.copilot_request_times) >= 10:
            return False
        record.copilot_request_times.append(now)
        return True

    def get_export(self, run_id: str, filename: str) -> Path | None:
        record = self.store.get(run_id)
        if record is None or record.status != RunStatus.SUCCEEDED or not record.export_dir:
            return None
        path = record.export_dir / filename
        return path if path.is_file() else None

    @staticmethod
    def _build_commit() -> str | None:
        value = os.getenv("RAILACCESS_BUILD_COMMIT", "").strip().lower()
        if len(value) == 40 and all(character in "0123456789abcdef" for character in value):
            return value
        return None

    @staticmethod
    def _checksum(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def create_submission_package(self, run_id: str) -> SubmissionPackageRecord:
        record = self.store.get(run_id)
        if record is None:
            raise SubmissionPackageError("run_not_found", f"No run exists with id {run_id}.")
        report = record.validation_report
        if (
            record.status != RunStatus.SUCCEEDED
            or record.schedule is None
            or record.export_dir is None
            or report is None
            or report.status.value != "unverified"
            or report.feasible is not None
            or report.hard_violations
        ):
            raise SubmissionPackageError(
                "submission_unavailable",
                "A submission package requires a locally clean, unverified succeeded run.",
            )
        build_commit = self._build_commit()
        if build_commit is None:
            raise SubmissionPackageError(
                "submission_provenance_unavailable",
                "Set RAILACCESS_BUILD_COMMIT to the full 40-character Git commit before creating a submission package.",
            )
        expected_inputs = set(INPUT_TABLES)
        if set(record.input_instance.source.file_checksums) != expected_inputs:
            raise SubmissionPackageError(
                "submission_provenance_unavailable",
                "This run does not retain checksums for all eight original input CSVs.",
            )
        export_names = ("SCHEDULE_ACCESS.csv", "SCHEDULE_OCCUPANCY.csv", "RESULTS.csv")
        export_paths = {name: record.export_dir / name for name in export_names}
        if not all(path.is_file() for path in export_paths.values()):
            raise SubmissionPackageError(
                "submission_unavailable",
                "The required export CSVs are no longer available for this run.",
            )

        package_id = str(uuid4())
        package_dir = record.export_dir / f"submission-{package_id}"
        try:
            package_dir.mkdir()
            manifest = SubmissionManifest(
                package_id=package_id,
                run_id=record.run_id,
                schedule_id=record.schedule.schedule_id,
                scenario=record.scenario,
                created_at=utc_now(),
                build_commit=build_commit,
                input_checksums=dict(sorted(record.input_instance.source.file_checksums.items())),
                output_checksums={name: self._checksum(path) for name, path in export_paths.items()},
                input_row_counts=InputInstanceSummary.from_instance(record.input_instance).row_counts,
                local_preflight_report=report.model_copy(deep=True),
            )
            manifest_path = package_dir / "submission-manifest.json"
            manifest_path.write_text(json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
            bundle_path = package_dir / "submission-package.zip"
            with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for filename in export_names:
                    archive.write(export_paths[filename], arcname=filename)
                archive.write(manifest_path, arcname=manifest_path.name)
        except Exception as error:
            shutil.rmtree(package_dir, ignore_errors=True)
            raise SubmissionPackageError("submission_package_failed", f"Could not create the submission package: {error}") from error

        package = SubmissionPackageRecord(manifest=manifest, directory=package_dir, bundle_path=bundle_path)
        record.submission_packages[package_id] = package
        record.updated_at = utc_now()
        return package

    def get_submission_package(self, run_id: str, package_id: str) -> SubmissionPackageRecord:
        record = self.store.get(run_id)
        if record is None:
            raise SubmissionPackageError("run_not_found", f"No run exists with id {run_id}.")
        package = record.submission_packages.get(package_id)
        if package is None:
            raise SubmissionPackageError("submission_package_not_found", f"No submission package {package_id} exists for this run.")
        return package

    def record_organiser_evidence(
        self, run_id: str, package_id: str, payload: OrganiserEvidenceInput
    ) -> SubmissionPackageRecord:
        record = self.store.get(run_id)
        package = self.get_submission_package(run_id, package_id)
        assert record is not None  # get_submission_package has already checked this.
        if package.organiser_evidence is not None:
            raise SubmissionPackageError(
                "organiser_evidence_exists",
                "This submission package already has organiser evidence. Create a new package for another upload.",
            )
        used_attempts = {
            item.organiser_evidence.attempt_number
            for item in record.submission_packages.values()
            if item.organiser_evidence is not None
        }
        if payload.attempt_number in used_attempts:
            raise SubmissionPackageError(
                "organiser_attempt_duplicate",
                f"Attempt {payload.attempt_number} is already recorded for this live run.",
            )
        evidence = OrganiserEvidence(**payload.model_dump(), recorded_at=utc_now())
        evidence_path = package.directory / "organiser-evidence.json"
        evidence_record = {
            "submission_manifest": package.manifest.model_dump(mode="json"),
            "organiser_evidence": evidence.model_dump(mode="json"),
        }
        evidence_path.write_text(json.dumps(evidence_record, indent=2) + "\n", encoding="utf-8")
        package.organiser_evidence = evidence
        package.evidence_record_path = evidence_path
        record.updated_at = utc_now()
        return package

    def get_evidence_record(self, run_id: str, package_id: str) -> Path:
        package = self.get_submission_package(run_id, package_id)
        if package.evidence_record_path is None or not package.evidence_record_path.is_file():
            raise SubmissionPackageError(
                "organiser_evidence_unavailable",
                "Record organiser metadata before downloading the combined evidence record.",
            )
        return package.evidence_record_path

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
