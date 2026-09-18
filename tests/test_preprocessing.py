"""Regression tests for the single shared solver/preflight preparation step."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.domain.models import NatureOfWorks
from app.domain.preprocessing import PreparationError, prepare_instance, require_prepared
from app.ingestion.csv_loader import load_instance


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DATA = ROOT / "data" / "public-instance"


def bundle_copy():
    return load_instance(PUBLIC_DATA).model_copy(deep=True)


def finding_details(result) -> list[str]:
    return [finding.detail for finding in result.findings]


def test_public_instance_prepares_complete_canonical_footprints() -> None:
    prepared = require_prepared(bundle_copy())

    assert len(prepared.activities) == 54
    assert prepared.calendar.horizon_weeks == 30
    assert all(item.candidate_weeks[0] == item.planned_start_week for item in prepared.activities)
    assert all(item.base_locations <= item.closure_locations for item in prepared.activities)


def test_live_interchange_expands_but_non_live_work_stays_line_local() -> None:
    prepared = require_prepared(bundle_copy())
    live = next(
        item
        for item in prepared.activities
        if item.project.nature_of_activity is NatureOfWorks.LIVE
        and "H01_H02" in f"{item.activity.start_location_id},{item.activity.end_location_id}"
    )
    non_live = next(
        item
        for item in prepared.activities
        if item.project.nature_of_activity is not NatureOfWorks.LIVE
    )

    assert {location.split(":")[1] for location in live.closure_locations} == {"ALP", "BET"}
    assert len({location.rsplit(":", 1)[1] for location in live.closure_locations}) == 2
    assert {location.split(":")[1] for location in non_live.closure_locations} == {
        non_live.route.line_code
    }


def test_preparation_collects_cross_file_findings_with_source_context() -> None:
    bundle = bundle_copy()
    duplicate_project = bundle.projects[0].model_copy(deep=True)
    bundle.projects.append(duplicate_project)
    bundle.activities[0].contract_number = "UNKNOWN"
    bundle.activities[1].predecessor_activity_id = "MISSING"
    bundle.activities[2].start_location_id = "SEC:ALP:UNKNOWN:EB"
    bundle.parameters[1].value = "not-a-number"

    result = prepare_instance(bundle)

    assert result.prepared is None
    details = finding_details(result)
    assert any("duplicate contract" in detail for detail in details)
    assert any("unknown contract" in detail for detail in details)
    assert any("unknown predecessor" in detail for detail in details)
    assert any("malformed SEC working section" in detail for detail in details)
    assert any("horizon_weeks" in detail for detail in details)
    assert all(finding.detail for finding in result.findings)
    assert any(
        finding.source_file == "08_ACTIVITY_DETAILS.csv"
        and finding.row is not None
        and finding.field is not None
        for finding in result.findings
    )
    with pytest.raises(PreparationError) as error:
        require_prepared(bundle)
    assert len(error.value.findings) == len(result.findings)


def test_preparation_rejects_cycles_missing_supply_and_out_of_horizon_dates() -> None:
    bundle = bundle_copy()
    baseline = require_prepared(bundle_copy())
    removed_location = next(item for item in baseline.activities if item.activity.activity_id == "A001")
    bundle.location_supply = [
        item for item in bundle.location_supply if item.location_id != next(iter(removed_location.base_locations))
    ]
    bundle.activities[2].predecessor_activity_id = bundle.activities[3].activity_id
    bundle.activities[3].predecessor_activity_id = bundle.activities[2].activity_id
    bundle.activities[4].planned_start_date = date(2030, 1, 1)

    details = finding_details(prepare_instance(bundle))

    assert any("Predecessor cycle" in detail for detail in details)
    assert any("absent from supply" in detail for detail in details)
    assert any("outside the planning horizon" in detail for detail in details)


def test_preparation_reports_remaining_duplicate_type_and_parameter_failures() -> None:
    bundle = bundle_copy()
    bundle.activities[0].activity_type = "Construction"
    bundle.activities.append(bundle.activities[0].model_copy(deep=True))
    bundle.location_supply.append(bundle.location_supply[0].model_copy(deep=True))
    bundle.buffer_locations.append(bundle.buffer_locations[0].model_copy(deep=True))
    bundle.parameters[0].value = "not-a-date"

    result = prepare_instance(bundle)
    details = finding_details(result)

    assert result.prepared is None
    assert any("activity_type does not match" in detail for detail in details)
    assert any("duplicate activity" in detail for detail in details)
    assert any("duplicate location ID" in detail for detail in details)
    assert any("duplicate nature" in detail for detail in details)
    assert any("horizon_start must be an ISO date" in detail for detail in details)
