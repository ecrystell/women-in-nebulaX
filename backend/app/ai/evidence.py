"""Build small deterministic evidence envelopes for the copilot.

The functions here are the data-minimisation boundary: callers must choose one
evidence kind and this module never returns raw CSV rows, bytes, exports, or a
complete hidden schedule.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.api.schemas import (
    ActivityEvidence,
    CapacityHotspot,
    CapacityHotspotsEvidence,
    ContractResult,
    EvidenceEnvelope,
    EvidenceKind,
    EvidenceValidation,
    HandoverEvidence,
    Placement,
    ValidationReport,
)
from app.domain.models import Scenario
from app.domain.preprocessing import PreparedInstance


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validation(report: ValidationReport) -> EvidenceValidation:
    return EvidenceValidation(
        status=report.status,
        feasible=report.feasible,
        hard_violation_count=len(report.hard_violations),
        message=report.message,
    )


def _location_label(location_id: str) -> str:
    """Translate compact CSV location IDs into controller-facing language."""

    parts = location_id.split(":")
    if len(parts) != 4:
        return location_id
    kind_code, line_code, place_code, bound_code = parts
    kind = {"PLAT": "Platform", "SEC": "Tunnel sector"}.get(kind_code, kind_code)
    line = {"ALP": "Line Alpha", "BET": "Line Beta"}.get(line_code, f"Line {line_code}")
    bound = {"EB": "eastbound", "WB": "westbound"}.get(bound_code, bound_code)
    if "_" in place_code:
        start, end = place_code.split("_", maxsplit=1)
        place = f"between {start} and {end}"
    elif place_code.startswith("H"):
        place = f"at interchange {place_code}"
    else:
        place = f"at station {place_code}"
    return f"{kind} on {line}, {place}, {bound}"


def _placement_summary(placement: Placement) -> str:
    """Make selected-activity placement evidence readable for a controller."""

    eclo = "with early closure / late opening" if placement.eclo else "without early closure / late opening"
    locations = "; ".join(_location_label(value.location_id) for value in placement.occupancies)
    groups = ", ".join(sorted({value.co_share_group for value in placement.occupancies}))
    return (
        f"Week {placement.week}, access night {placement.access_night}, {eclo}, "
        f"possession group {groups}: {locations}"
    )


def capacity_hotspots(
    prepared: PreparedInstance,
    schedule_placements: list[Placement],
    scenario: Scenario,
    *,
    limit: int = 10,
) -> list[CapacityHotspot]:
    """Return possession pressure using the same co-share counting as preflight."""

    groups: dict[tuple[str, int], dict[str, set[str]]] = {}
    for placement in schedule_placements:
        for occupancy in placement.occupancies:
            bucket = groups.setdefault((occupancy.location_id, placement.week), {})
            bucket.setdefault(occupancy.co_share_group, set()).add(placement.activity_id)

    items: list[CapacityHotspot] = []
    for (location_id, week), by_group in groups.items():
        count = len(by_group)
        supply = prepared.supply.get(location_id, 0)
        allowed = supply if scenario in {Scenario.A, Scenario.B} else supply + 1
        excess = max(0, count - allowed)
        utilisation = count / supply if supply else float(count)
        items.append(
            CapacityHotspot(
                location_id=location_id,
                location_label=_location_label(location_id),
                week=week,
                possession_group_count=count,
                supply_capacity=supply,
                allowed_possessions=allowed,
                excess_access_nights=excess,
                utilisation=utilisation,
                co_share_groups=sorted(by_group),
                activity_ids=sorted({activity_id for members in by_group.values() for activity_id in members}),
            )
        )
    return sorted(
        items,
        key=lambda item: (-item.excess_access_nights, -item.utilisation, item.location_id, item.week),
    )[:limit]


def _envelope(
    *,
    run_id: str,
    schedule_id: str,
    scenario: Scenario,
    report: ValidationReport,
    payload: ActivityEvidence | CapacityHotspotsEvidence | HandoverEvidence,
) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        run_id=run_id,
        schedule_id=schedule_id,
        scenario=scenario,
        generated_at=_now(),
        validation=_validation(report),
        payload=payload,
    )


def activity_evidence(
    *,
    run_id: str,
    schedule_id: str,
    scenario: Scenario,
    prepared: PreparedInstance,
    schedule_placements: list[Placement],
    contract_results: list[ContractResult],
    report: ValidationReport,
    activity_id: str,
) -> EvidenceEnvelope | None:
    item = prepared.activities_by_id.get(activity_id)
    if item is None:
        return None
    placements = [placement for placement in schedule_placements if placement.activity_id == activity_id]
    result = next((value for value in contract_results if value.contract_number == item.activity.contract_number), None)
    findings = [
        finding
        for finding in report.hard_violations
        if finding.activity_ids is not None and activity_id in finding.activity_ids
    ]
    return _envelope(
        run_id=run_id,
        schedule_id=schedule_id,
        scenario=scenario,
        report=report,
        payload=ActivityEvidence(
            kind=EvidenceKind.ACTIVITY,
            activity_id=activity_id,
            contract_number=item.activity.contract_number,
            activity_type=item.activity.activity_type,
            access_type=item.project.access_type.value,
            nature_of_activity=item.project.nature_of_activity.value,
            total_accesses_required=item.activity.total_accesses,
            planned_start_week=item.planned_start_week,
            predecessor_activity_id=item.activity.predecessor_activity_id,
            placements=placements,
            closure_footprint=sorted(item.closure_locations),
            closure_footprint_labels=[_location_label(location_id) for location_id in sorted(item.closure_locations)],
            placement_summaries=[_placement_summary(placement) for placement in placements],
            contract_result=result,
            local_findings=findings,
        ),
    )


def hotspots_evidence(
    *,
    run_id: str,
    schedule_id: str,
    scenario: Scenario,
    prepared: PreparedInstance,
    schedule_placements: list[Placement],
    report: ValidationReport,
) -> EvidenceEnvelope:
    return _envelope(
        run_id=run_id,
        schedule_id=schedule_id,
        scenario=scenario,
        report=report,
        payload=CapacityHotspotsEvidence(
            kind=EvidenceKind.CAPACITY_HOTSPOTS,
            hotspots=capacity_hotspots(prepared, schedule_placements, scenario),
        ),
    )


def handover_evidence(
    *,
    run_id: str,
    schedule_id: str,
    scenario: Scenario,
    prepared: PreparedInstance,
    schedule_placements: list[Placement],
    contract_results: list[ContractResult],
    report: ValidationReport,
) -> EvidenceEnvelope:
    hotspots = capacity_hotspots(prepared, schedule_placements, scenario)
    return _envelope(
        run_id=run_id,
        schedule_id=schedule_id,
        scenario=scenario,
        report=report,
        payload=HandoverEvidence(
            kind=EvidenceKind.HANDOVER,
            placement_count=len(schedule_placements),
            scheduled_activity_count=len({item.activity_id for item in schedule_placements}),
            contract_results=contract_results,
            local_score_components=report.soft_scores,
            top_hotspots=hotspots[:3],
        ),
    )
