"""Public API schemas derived from the approved integration contract."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import (
    AccessAssignment,
    ActivityRecord,
    BufferLocationRecord,
    ContractResult,
    InstanceBundle,
    LineRecord,
    LocationSupplyRecord,
    OccupancyAssignment,
    ParameterRecord,
    ProjectRecord,
    Scenario,
    ScenarioSchedule,
    SectorRecord,
    StationRecord,
)
from app.validation.adapter import ValidationReport as DomainValidationReport


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InputSource(ApiModel):
    instance_id: str
    received_at: datetime
    fixture: bool = False
    file_checksums: dict[str, str] = Field(default_factory=dict)


class InputInstance(ApiModel):
    """The full parsed input package; retained in memory, never persisted."""

    source: InputSource
    lines: list[LineRecord]
    stations: list[StationRecord]
    sectors: list[SectorRecord]
    location_supply: list[LocationSupplyRecord]
    buffer_locations: list[BufferLocationRecord]
    parameters: list[ParameterRecord]
    projects: list[ProjectRecord]
    activities: list[ActivityRecord]

    @classmethod
    def from_bundle(cls, bundle: InstanceBundle, source: InputSource) -> "InputInstance":
        return cls(source=source, **bundle.model_dump())

    def to_bundle(self) -> InstanceBundle:
        return InstanceBundle.model_validate(self.model_dump(exclude={"source"}))


class InputInstanceSummary(ApiModel):
    instance_id: str
    fixture: bool
    row_counts: dict[str, int]

    @classmethod
    def from_instance(cls, instance: InputInstance) -> "InputInstanceSummary":
        table_names = (
            "lines",
            "stations",
            "sectors",
            "location_supply",
            "buffer_locations",
            "parameters",
            "projects",
            "activities",
        )
        return cls(
            instance_id=instance.source.instance_id,
            fixture=instance.source.fixture,
            row_counts={name: len(getattr(instance, name)) for name in table_names},
        )


class PlacementKey(ApiModel):
    activity_id: str
    access_seq: int = Field(gt=0)


class Occupancy(ApiModel):
    location_id: str
    co_share_group: str


class Placement(PlacementKey):
    week: int = Field(gt=0)
    access_night: int = Field(gt=0)
    eclo: Literal[0, 1]
    occupancies: list[Occupancy]


class Schedule(ApiModel):
    schedule_id: str
    input_instance_id: str
    scenario: Scenario
    placements: list[Placement]
    contract_results: list[ContractResult]
    generated_at: datetime

    @model_validator(mode="after")
    def has_one_scenario_and_unique_placements(self) -> "Schedule":
        keys = [(placement.activity_id, placement.access_seq) for placement in self.placements]
        if len(keys) != len(set(keys)):
            raise ValueError("each placement key must occur at most once")
        if any(result.scenario != self.scenario for result in self.contract_results):
            raise ValueError("every contract result must use the schedule scenario")
        return self

    @classmethod
    def from_domain(
        cls,
        schedule: ScenarioSchedule,
        *,
        schedule_id: str,
        input_instance_id: str,
        generated_at: datetime,
    ) -> "Schedule":
        occupancies_by_activity_week: dict[tuple[str, int], list[Occupancy]] = {}
        for occupancy in schedule.occupancy_assignments:
            key = (occupancy.activity_id, occupancy.week)
            occupancies_by_activity_week.setdefault(key, []).append(
                Occupancy(location_id=occupancy.location_id, co_share_group=occupancy.co_share_group)
            )
        placements = [
            Placement(
                activity_id=assignment.activity_id,
                access_seq=assignment.access_seq,
                week=assignment.week,
                access_night=assignment.access_night,
                eclo=assignment.eclo,
                occupancies=occupancies_by_activity_week.get((assignment.activity_id, assignment.week), []),
            )
            for assignment in schedule.access_assignments
        ]
        return cls(
            schedule_id=schedule_id,
            input_instance_id=input_instance_id,
            scenario=schedule.scenario,
            placements=placements,
            contract_results=schedule.contract_results,
            generated_at=generated_at,
        )

    def to_domain(self) -> ScenarioSchedule:
        access_assignments: list[AccessAssignment] = []
        occupancy_assignments: list[OccupancyAssignment] = []
        for placement in self.placements:
            access_assignments.append(
                AccessAssignment(
                    activity_id=placement.activity_id,
                    access_seq=placement.access_seq,
                    week=placement.week,
                    eclo=placement.eclo,
                    access_night=placement.access_night,
                )
            )
            occupancy_assignments.extend(
                OccupancyAssignment(
                    activity_id=placement.activity_id,
                    week=placement.week,
                    location_id=occupancy.location_id,
                    co_share_group=occupancy.co_share_group,
                )
                for occupancy in placement.occupancies
            )
        return ScenarioSchedule(
            scenario=self.scenario,
            access_assignments=access_assignments,
            occupancy_assignments=occupancy_assignments,
            contract_results=self.contract_results,
        )


class Violation(ApiModel):
    rule: str
    severity: Literal["hard", "soft"]
    detail: str
    activity_ids: list[str] | None = None
    location_ids: list[str] | None = None
    week: int | None = Field(default=None, gt=0)
    source_file: str | None = None
    row: int | None = Field(default=None, ge=2)
    field: str | None = None
    co_share_group: str | None = None
    derived_footprint: list[str] | None = None
    input_values: dict[str, str | int | float | bool | None] | None = None


class ValidatorMetadata(ApiModel):
    name: str | None = None
    version: str | None = None
    executed_at: datetime | None = None


class ValidationStatus(str, Enum):
    UNAVAILABLE = "unavailable"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


class ValidationReport(ApiModel):
    schedule_id: str | None = None
    status: ValidationStatus
    feasible: bool | None = None
    message: str
    hard_violations: list[Violation] = Field(default_factory=list)
    soft_scores: dict[str, Any] = Field(default_factory=dict)
    detail: dict[str, Any] = Field(default_factory=dict)
    validator: ValidatorMetadata = Field(default_factory=ValidatorMetadata)

    @model_validator(mode="after")
    def verification_state_is_truthful(self) -> "ValidationReport":
        if self.status != ValidationStatus.VERIFIED and self.feasible is not None:
            raise ValueError("only verified reports may contain a feasibility decision")
        if self.feasible is True and self.hard_violations:
            raise ValueError("a feasible report cannot contain hard violations")
        return self

    @classmethod
    def from_domain(
        cls, report: DomainValidationReport, *, schedule_id: str | None = None
    ) -> "ValidationReport":
        return cls(
            schedule_id=schedule_id,
            status=ValidationStatus(report.status.value),
            feasible=report.feasible,
            message=report.message,
            hard_violations=[
                Violation(
                    rule=str(item.get("rule", "unknown")),
                    severity="hard",
                    detail=str(item.get("detail", "")),
                    activity_ids=(
                        [str(value) for value in item["activity_ids"]]
                        if isinstance(item.get("activity_ids"), list)
                        else None
                    ),
                    location_ids=(
                        [str(value) for value in item["location_ids"]]
                        if isinstance(item.get("location_ids"), list)
                        else None
                    ),
                    week=(int(item["week"]) if item.get("week") is not None else None),
                    source_file=(str(item["source_file"]) if item.get("source_file") is not None else None),
                    row=(int(item["row"]) if item.get("row") is not None else None),
                    field=(str(item["field"]) if item.get("field") is not None else None),
                    co_share_group=(
                        str(item["co_share_group"]) if item.get("co_share_group") is not None else None
                    ),
                    derived_footprint=(
                        [str(value) for value in item["derived_footprint"]]
                        if isinstance(item.get("derived_footprint"), list)
                        else None
                    ),
                    input_values=(
                        item["input_values"] if isinstance(item.get("input_values"), dict) else None
                    ),
                )
                for item in report.hard_violations
            ],
            soft_scores=report.soft_scores,
            detail=report.detail,
        )


class SupplyOverride(ApiModel):
    location_id: str
    week: int = Field(gt=0)
    supply_capacity: int = Field(ge=0)


class ScenarioChange(ApiModel):
    change_id: str
    base_schedule_id: str
    scenario: Scenario
    supply_overrides: list[SupplyOverride] = Field(default_factory=list)
    locked_placements: list[PlacementKey] = Field(default_factory=list)
    requested_by: str
    confirmed_at: datetime | None = None
    rationale: str | None = None


class ApiFieldError(ApiModel):
    field: str
    message: str


class ScenarioChangeDraftRequest(ApiModel):
    """Bounded controller prose for the public-fixture draft parser."""

    text: str = Field(min_length=1, max_length=1_000)


class ScenarioChangeDraftStatus(str, Enum):
    READY = "ready"
    NEEDS_REVIEW = "needs_review"


class RecoveryDraftSource(str, Enum):
    SUPPLY_CSV = "supply_csv"
    NATURAL_LANGUAGE = "natural_language"
    MANUAL_REVIEW = "manual_review"


class ScenarioChangeDraftUpdate(ApiModel):
    """Controller edits made during recovery review; never a confirmation."""

    supply_overrides: list[SupplyOverride] = Field(default_factory=list, max_length=2_000)
    locked_placements: list[PlacementKey] = Field(default_factory=list, max_length=2_000)
    rationale: str | None = Field(default=None, max_length=500)


class ScenarioChangeDraft(ApiModel):
    """A review-only interpretation; it is never a confirmed change."""

    draft_id: str
    change: ScenarioChange
    source: RecoveryDraftSource
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    unresolved_references: list[str] = Field(default_factory=list, max_length=20)
    field_errors: list[ApiFieldError] = Field(default_factory=list)
    evidence_version: Literal["1"] = "1"
    status: ScenarioChangeDraftStatus


class DemoRecoveryRequest(ApiModel):
    """Optionally tie a fixed public replay to a reviewed draft."""

    draft_id: str | None = Field(default=None, min_length=1, max_length=100)


class PlacementChange(ApiModel):
    key: PlacementKey
    kind: Literal["unchanged", "moved", "added", "removed"]
    before: Placement | None = None
    after: Placement | None = None
    changed_fields: list[Literal["week", "access_night", "eclo", "occupancies"]] = Field(
        default_factory=list
    )


class ScheduleDiff(ApiModel):
    baseline_schedule_id: str
    recovered_schedule_id: str
    placement_changes: list[PlacementChange]
    unchanged_count: int = Field(ge=0)
    moved_count: int = Field(ge=0)
    score_delta: dict[str, float] | None = None
    completion_delta: dict[str, float] | None = None


class SolverDiagnostics(ApiModel):
    """Non-authoritative CP-SAT execution evidence for one API run."""

    status: str
    wall_time_seconds: float = Field(ge=0)
    time_limit_seconds: float = Field(gt=0)
    recovery_source: Literal["reoptimized", "incumbent_not_worse", "incumbent_fallback"] | None = None


class RunStatus(str, Enum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class FeatureCapability(ApiModel):
    available: bool
    code: str | None = None
    message: str
    supported_scenarios: list[Scenario] = Field(default_factory=list)


class ScenarioCapability(FeatureCapability):
    scenario: Scenario


class CapabilityReport(ApiModel):
    scenarios: list[ScenarioCapability] = Field(min_length=3, max_length=3)
    recovery: FeatureCapability
    public_demo_recovery: FeatureCapability
    disruption_drafts: FeatureCapability


class EvidenceKind(str, Enum):
    ACTIVITY = "activity"
    CAPACITY_HOTSPOTS = "capacity_hotspots"
    HANDOVER = "handover"


class EvidenceValidation(ApiModel):
    """Small, non-authoritative validation context safe to show beside AI text."""

    status: ValidationStatus
    feasible: bool | None = None
    hard_violation_count: int = Field(ge=0)
    message: str


class ActivityEvidence(ApiModel):
    kind: Literal[EvidenceKind.ACTIVITY]
    activity_id: str
    contract_number: str
    activity_type: str
    access_type: str
    nature_of_activity: str
    total_accesses_required: int = Field(gt=0)
    planned_start_week: int = Field(gt=0)
    predecessor_activity_id: str | None = None
    placements: list[Placement]
    closure_footprint: list[str]
    closure_footprint_labels: list[str]
    placement_summaries: list[str]
    contract_result: ContractResult | None = None
    local_findings: list[Violation] = Field(default_factory=list)


class CapacityHotspot(ApiModel):
    location_id: str
    location_label: str
    week: int = Field(gt=0)
    possession_group_count: int = Field(ge=0)
    supply_capacity: int = Field(ge=0)
    allowed_possessions: int = Field(ge=0)
    excess_access_nights: int = Field(ge=0)
    utilisation: float = Field(ge=0)
    co_share_groups: list[str]
    activity_ids: list[str]


class CapacityHotspotsEvidence(ApiModel):
    kind: Literal[EvidenceKind.CAPACITY_HOTSPOTS]
    hotspots: list[CapacityHotspot] = Field(max_length=10)


class HandoverEvidence(ApiModel):
    kind: Literal[EvidenceKind.HANDOVER]
    placement_count: int = Field(ge=0)
    scheduled_activity_count: int = Field(ge=0)
    contract_results: list[ContractResult]
    local_score_components: dict[str, Any]
    top_hotspots: list[CapacityHotspot] = Field(max_length=3)


EvidencePayload = Annotated[
    ActivityEvidence | CapacityHotspotsEvidence | HandoverEvidence,
    Field(discriminator="kind"),
]


class EvidenceEnvelope(ApiModel):
    evidence_version: Literal["1"] = "1"
    run_id: str
    schedule_id: str
    scenario: Scenario
    generated_at: datetime
    validation: EvidenceValidation
    payload: EvidencePayload


class CopilotMode(str, Enum):
    ACTIVITY_EXPLANATION = "activity_explanation"
    CAPACITY_HOTSPOTS = "capacity_hotspots"
    HANDOVER_SUMMARY = "handover_summary"


class CopilotRequest(ApiModel):
    mode: CopilotMode
    activity_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def activity_is_required_only_for_activity_explanations(self) -> "CopilotRequest":
        if self.mode is CopilotMode.ACTIVITY_EXPLANATION and not self.activity_id:
            raise ValueError("activity_id is required for an activity explanation")
        if self.mode is not CopilotMode.ACTIVITY_EXPLANATION and self.activity_id is not None:
            raise ValueError("activity_id is supported only for an activity explanation")
        return self


class CopilotResponse(ApiModel):
    mode: CopilotMode
    answer: str = Field(min_length=1, max_length=2000)
    evidence: EvidenceEnvelope
    model: str
    generated_at: datetime
    verification_disclaimer: Literal[
        "Organiser verification is unavailable or unverified; this explanation does not establish feasibility."
    ] = "Organiser verification is unavailable or unverified; this explanation does not establish feasibility."


class RunProblem(ApiModel):
    code: str
    message: str


class OrganiserReportedOutcome(str, Enum):
    UNKNOWN = "unknown"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class OrganiserEvidenceInput(ApiModel):
    """Human-entered website metadata; never parsed as organiser verification."""

    attempt_number: int = Field(ge=1, le=5)
    submitted_at: datetime
    reported_outcome: OrganiserReportedOutcome
    report_reference: str | None = Field(default=None, max_length=500)
    report_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    note: str | None = Field(default=None, max_length=2000)


class OrganiserEvidence(OrganiserEvidenceInput):
    recorded_at: datetime


class SubmissionManifest(ApiModel):
    schema_version: Literal["1"] = "1"
    package_id: str
    run_id: str
    schedule_id: str
    scenario: Scenario
    created_at: datetime
    build_commit: str
    input_checksums: dict[str, str]
    output_checksums: dict[str, str]
    input_row_counts: dict[str, int]
    local_preflight_report: ValidationReport


class SubmissionPackageSummary(ApiModel):
    package_id: str
    run_id: str
    schedule_id: str
    scenario: Scenario
    created_at: datetime
    build_commit: str
    organiser_evidence: OrganiserEvidence | None = None


class RunView(ApiModel):
    run_id: str
    status: RunStatus
    scenario: Scenario
    input_instance: InputInstanceSummary
    created_at: datetime
    updated_at: datetime
    recovery_of_run_id: str | None = None
    scenario_change: ScenarioChange | None = None
    schedule: Schedule | None = None
    validation_report: ValidationReport | None = None
    schedule_diff: ScheduleDiff | None = None
    solver_diagnostics: SolverDiagnostics | None = None
    problem: RunProblem | None = None
    demo: bool = False
    demo_notice: str | None = None
    submission_packages: list[SubmissionPackageSummary] = Field(default_factory=list)


class ApiError(ApiModel):
    code: str
    message: str
    field_errors: list[ApiFieldError] = Field(default_factory=list)


class ApiErrorResponse(ApiModel):
    request_id: str
    error: ApiError
