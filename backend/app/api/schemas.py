"""Public API schemas derived from the approved integration contract."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

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


class RunStatus(str, Enum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class RunProblem(ApiModel):
    code: str
    message: str


class RunView(ApiModel):
    run_id: str
    status: RunStatus
    scenario: Scenario
    input_instance: InputInstanceSummary
    created_at: datetime
    updated_at: datetime
    recovery_of_run_id: str | None = None
    schedule: Schedule | None = None
    validation_report: ValidationReport | None = None
    schedule_diff: ScheduleDiff | None = None
    problem: RunProblem | None = None


class ApiFieldError(ApiModel):
    field: str
    message: str


class ApiError(ApiModel):
    code: str
    message: str
    field_errors: list[ApiFieldError] = Field(default_factory=list)


class ApiErrorResponse(ApiModel):
    request_id: str
    error: ApiError
