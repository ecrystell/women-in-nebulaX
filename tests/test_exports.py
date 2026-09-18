from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from app.domain.models import (
    AccessAssignment,
    ContractResult,
    OccupancyAssignment,
    Scenario,
    ScenarioSchedule,
)
from app.exports.csv_writer import ACCESS_HEADERS, OCCUPANCY_HEADERS, RESULT_HEADERS, write_submission


def test_exports_have_exact_official_headers(tmp_path: Path) -> None:
    schedule = ScenarioSchedule(
        scenario=Scenario.A,
        access_assignments=[AccessAssignment(activity_id="A001", access_seq=1, week=1, eclo=0, access_night=1)],
        occupancy_assignments=[OccupancyAssignment(activity_id="A001", week=1, location_id="SEC:ALP:S01_S02:EB", co_share_group="b1")],
        contract_results=[ContractResult(scenario=Scenario.A, contract_number="C001", simulated_completion_date=date(2027, 1, 10), overrun_days=0)],
    )

    output_paths = write_submission(schedule, tmp_path)

    expected_headers = {
        "SCHEDULE_ACCESS.csv": ACCESS_HEADERS,
        "SCHEDULE_OCCUPANCY.csv": OCCUPANCY_HEADERS,
        "RESULTS.csv": RESULT_HEADERS,
    }
    for name, headers in expected_headers.items():
        with output_paths[name].open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            assert reader.fieldnames == headers
            row = next(reader)
            assert row

    assert (tmp_path / "RESULTS.csv").read_text(encoding="utf-8").splitlines()[1].startswith("A,C001,2027-01-10,0")


def test_schedule_rejects_mixed_result_scenarios() -> None:
    try:
        ScenarioSchedule(
            scenario=Scenario.A,
            access_assignments=[],
            occupancy_assignments=[],
            contract_results=[ContractResult(scenario=Scenario.B, contract_number="C001", simulated_completion_date=date(2027, 1, 10), overrun_days=0)],
        )
    except ValueError as error:
        assert "every contract result" in str(error)
    else:
        raise AssertionError("mixed scenario results must fail")


def test_public_sample_round_trips_through_canonical_contract(tmp_path: Path) -> None:
    sample_dir = Path(__file__).resolve().parents[1] / "data" / "public-instance" / "sample-submission"

    with (sample_dir / "SCHEDULE_ACCESS.csv").open(newline="", encoding="utf-8") as handle:
        access_assignments = [AccessAssignment.model_validate(row) for row in csv.DictReader(handle)]
    with (sample_dir / "SCHEDULE_OCCUPANCY.csv").open(newline="", encoding="utf-8") as handle:
        occupancy_assignments = [OccupancyAssignment.model_validate(row) for row in csv.DictReader(handle)]
    with (sample_dir / "RESULTS.csv").open(newline="", encoding="utf-8") as handle:
        contract_results = [ContractResult.model_validate(row) for row in csv.DictReader(handle)]

    schedule = ScenarioSchedule(
        scenario=Scenario.A,
        access_assignments=access_assignments,
        occupancy_assignments=occupancy_assignments,
        contract_results=contract_results,
    )
    exported = write_submission(schedule, tmp_path)

    for name in exported:
        assert exported[name].read_text(encoding="utf-8") == (sample_dir / name).read_text(encoding="utf-8")
