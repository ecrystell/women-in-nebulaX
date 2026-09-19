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
    CapabilityReport,
    FeatureCapability,
    InputInstance,
    InputInstanceSummary,
    InputSource,
    RunProblem,
    RunStatus,
    RunView,
    OrganiserEvidence,
    OrganiserEvidenceInput,
    PlacementChange,
    ScenarioChange,
    ScenarioCapability,
    ScenarioChangeDraft,
    ScenarioChangeDraftStatus,
    Schedule,
    ScheduleDiff,
    SubmissionManifest,
    SubmissionPackageSummary,
    ValidationReport,
)
from app.ingestion.csv_loader import INPUT_TABLES, load_instance
from app.domain.models import Scenario, ScenarioSchedule
from app.domain.preprocessing import PreparedInstance, prepare_instance
from app.ai import evidence as evidence_builder
from app.api.schemas import CopilotMode, EvidenceEnvelope
from app.exports.csv_writer import write_submission
from app.validation.adapter import OfficialValidatorAdapter
from app.validation.preflight import load_submission, preparation_report, validate_schedule
from app.api.solver_contract import ScenarioUnavailable, SolverInputInvalid, SolverUnavailable


def _public_data_root() -> Path:
    """Locate vendored public data in both source and single-container layouts."""

    module_path = Path(__file__).resolve()
    candidates = (module_path.parents[3] / "data", module_path.parents[2] / "data")
    return next((candidate for candidate in candidates if candidate.is_dir()), candidates[0])


PUBLIC_INSTANCE_DIR = _public_data_root() / "public-instance"
PUBLIC_SUBMISSION_DIR = PUBLIC_INSTANCE_DIR / "sample-submission"
DEMO_NOTICE = "Public demonstration fixture \u2014 not a newly optimised schedule."


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
    demo: bool = False
    demo_notice: str | None = None
    disruption_drafts: dict[str, ScenarioChangeDraft] = field(default_factory=dict, repr=False)
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
            scenario_change=self.scenario_change,
            schedule=self.schedule,
            validation_report=self.validation_report,
            schedule_diff=self.schedule_diff,
            problem=self.problem,
            demo=self.demo,
            demo_notice=self.demo_notice,
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
        demo: bool = False,
        demo_notice: str | None = None,
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
            demo=demo,
            demo_notice=demo_notice,
            validation_report=ValidationReport.from_domain(self.validator.status()),
        )
        self.store.add(record)
        return record

    @staticmethod
    def _fixture_checksums() -> dict[str, str] | None:
        """Return public input hashes only when the committed fixture is intact."""

        manifest_path = PUBLIC_INSTANCE_DIR / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            files = manifest["files"]
            expected = {name: files[name] for name in INPUT_TABLES}
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            return None
        actual: dict[str, str] = {}
        for name, expected_hash in expected.items():
            path = PUBLIC_INSTANCE_DIR / name
            if not path.is_file():
                return None
            # The manifest records upstream LF bytes. Git commonly checks the
            # public CSV fixtures out with CRLF on Windows, which is not a
            # semantic fixture change.
            normalized = path.read_bytes().replace(b"\r\n", b"\n")
            digest = hashlib.sha256(normalized).hexdigest()
            if digest != expected_hash:
                return None
            actual[name] = digest
        return actual

    def public_fixture_available(self) -> bool:
        return self._fixture_checksums() is not None and all(
            (PUBLIC_SUBMISSION_DIR / name).is_file()
            for name in ("SCHEDULE_ACCESS.csv", "SCHEDULE_OCCUPANCY.csv", "RESULTS.csv")
        )

    def capability_report(self, *, draft_parser_available: bool) -> CapabilityReport:
        declared = getattr(self.solver, "supported_scenarios", (Scenario.A,))
        supported = {Scenario(value) if isinstance(value, str) else value for value in declared}
        scenarios = [
            ScenarioCapability(
                scenario=scenario,
                available=scenario in supported,
                code=None if scenario in supported else "scenario_unavailable",
                message=(
                    "The active solver supports this scenario."
                    if scenario in supported
                    else f"Scenario {scenario.value} is unavailable until its approved solver policy is connected."
                ),
            )
            for scenario in (Scenario.A, Scenario.B, Scenario.C)
        ]
        recovery_available = bool(getattr(self.solver, "supports_recovery", False))
        public_demo = self.public_fixture_available()
        return CapabilityReport(
            scenarios=scenarios,
            recovery=FeatureCapability(
                available=recovery_available,
                code=None if recovery_available else "recovery_solver_unavailable",
                message=(
                    "The active solver supports confirmed recovery changes."
                    if recovery_available
                    else "Recovery optimisation is not connected yet; no revised live schedule can be created."
                ),
            ),
            public_demo_recovery=FeatureCapability(
                available=public_demo,
                code=None if public_demo else "public_demo_unavailable",
                message=(
                    "A public-fixture demonstration replay is available."
                    if public_demo
                    else "The committed public fixture is unavailable or failed its checksum check."
                ),
            ),
            disruption_drafts=FeatureCapability(
                available=public_demo and draft_parser_available,
                code=None if public_demo and draft_parser_available else "disruption_parser_unavailable",
                message=(
                    "Draft disruption parsing is available for the public fixture only."
                    if public_demo and draft_parser_available
                    else "Draft disruption parsing requires the intact public fixture and an enabled Vertex service."
                ),
            ),
        )

    def is_public_demo(self, record: RunRecord) -> bool:
        return (
            record.demo
            and record.input_instance.source.fixture
            and record.input_instance.source.instance_id == "public-fixture-v1"
            and self.public_fixture_available()
        )

    def create_public_demo_run(self) -> RunRecord:
        checksums = self._fixture_checksums()
        if checksums is None or not self.public_fixture_available():
            raise ValueError("The committed public fixture is unavailable or has changed.")
        bundle = load_instance(PUBLIC_INSTANCE_DIR)
        instance = InputInstance.from_bundle(
            bundle,
            InputSource(
                instance_id="public-fixture-v1",
                received_at=utc_now(),
                fixture=True,
                file_checksums=checksums,
            ),
        )
        record = self.create_run(instance, Scenario.A, demo=True, demo_notice=DEMO_NOTICE)
        preparation = prepare_instance(instance.to_bundle())
        if preparation.prepared is None:
            self.store.remove(record.run_id)
            raise ValueError("The committed public fixture failed shared preprocessing validation.")
        candidate = load_submission(PUBLIC_SUBMISSION_DIR)
        schedule_id = str(uuid4())
        report = ValidationReport.from_domain(
            validate_schedule(preparation.prepared, candidate), schedule_id=schedule_id
        )
        if report.hard_violations:
            self.store.remove(record.run_id)
            raise ValueError("The public demo schedule failed local preflight and cannot be replayed.")
        record.prepared_instance = preparation.prepared
        record.schedule = Schedule.from_domain(
            candidate,
            schedule_id=schedule_id,
            input_instance_id=instance.source.instance_id,
            generated_at=utc_now(),
        )
        # The baseline exposes the fixed demonstration change for review.  It
        # is never dispatched to a solver in this public-fixture replay.
        record.scenario_change = self._demo_change(record)
        record.validation_report = report
        record.status = RunStatus.SUCCEEDED
        record.updated_at = utc_now()
        return record

    @staticmethod
    def _unchanged_demo_diff(baseline: Schedule, recovered: Schedule) -> ScheduleDiff:
        changes = [
            PlacementChange(
                key={"activity_id": placement.activity_id, "access_seq": placement.access_seq},
                kind="unchanged",
                before=placement,
                after=placement,
            )
            for placement in baseline.placements
        ]
        return ScheduleDiff(
            baseline_schedule_id=baseline.schedule_id,
            recovered_schedule_id=recovered.schedule_id,
            placement_changes=changes,
            unchanged_count=len(changes),
            moved_count=0,
            score_delta={"demo_replay": 0.0},
            completion_delta={"overrun_days": 0.0},
        )

    @staticmethod
    def _demo_change(record: RunRecord) -> ScenarioChange:
        assert record.schedule is not None and record.prepared_instance is not None
        placement = next(item for item in record.schedule.placements if item.occupancies)
        location_id = placement.occupancies[0].location_id
        supply = record.prepared_instance.supply.get(location_id, 1)
        return ScenarioChange(
            change_id="public-demo-replay",
            base_schedule_id=record.schedule.schedule_id,
            scenario=record.scenario,
            supply_overrides=[
                {"location_id": location_id, "week": placement.week, "supply_capacity": max(1, supply - 1)}
            ],
            locked_placements=[{"activity_id": placement.activity_id, "access_seq": placement.access_seq}],
            requested_by="public-demo",
            confirmed_at=utc_now(),
            rationale="Fixed public-fixture recovery replay.",
        )

    def create_public_demo_replay(self, base_run_id: str, *, draft_id: str | None = None) -> RunRecord | None:
        base = self.store.get(base_run_id)
        if base is None or not self.is_public_demo(base) or base.schedule is None or base.prepared_instance is None:
            return None
        if draft_id is not None:
            draft = base.disruption_drafts.get(draft_id)
            if draft is None or draft.status is not ScenarioChangeDraftStatus.READY:
                return None
            if draft.change.base_schedule_id != base.schedule.schedule_id:
                return None
        change = self._demo_change(base)
        record = self.create_run(
            base.input_instance,
            base.scenario,
            recovery_of_run_id=base.run_id,
            scenario_change=change,
            demo=True,
            demo_notice=DEMO_NOTICE,
        )
        schedule_id = str(uuid4())
        candidate = base.schedule.to_domain()
        record.prepared_instance = base.prepared_instance
        record.schedule = Schedule.from_domain(
            candidate,
            schedule_id=schedule_id,
            input_instance_id=base.input_instance.source.instance_id,
            generated_at=utc_now(),
        )
        record.validation_report = ValidationReport.from_domain(
            validate_schedule(base.prepared_instance, candidate), schedule_id=schedule_id
        )
        if record.validation_report.hard_violations:
            self.store.remove(record.run_id)
            return None
        record.schedule_diff = self._unchanged_demo_diff(base.schedule, record.schedule)
        record.status = RunStatus.SUCCEEDED
        record.updated_at = utc_now()
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
        if record is None or record.demo or record.status != RunStatus.SUCCEEDED or not record.export_dir:
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
        if record.demo:
            raise SubmissionPackageError(
                "demo_submission_unavailable",
                "Public demonstration runs cannot create submission packages or organiser evidence.",
            )
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
        if record is not None and record.demo:
            raise SubmissionPackageError(
                "demo_submission_unavailable",
                "Public demonstration runs cannot record organiser submission evidence.",
            )
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
