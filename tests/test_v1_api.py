from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.run_service import RunService, SolverOutput
from app.api.schemas import ScenarioChange, ValidationReport, ValidationStatus
from app.domain.models import (
    AccessAssignment,
    ContractResult,
    OccupancyAssignment,
    Scenario,
    ScenarioSchedule,
)
from app.domain.preprocessing import PreparedInstance
from app.main import app
from app.solver.adapter import CpSatSolverAdapter
from app.validation.preflight import load_submission


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DATA = ROOT / "data" / "public-instance"
SAMPLE_SUBMISSION = PUBLIC_DATA / "sample-submission"
CLEAN_SCENARIO_A = ROOT / "sample_submission" / "scenario_a"


def public_files(exclude: str | None = None, replacement: tuple[str, bytes] | None = None) -> list[tuple[str, tuple[str, bytes, str]]]:
    payloads: list[tuple[str, tuple[str, bytes, str]]] = []
    for path in sorted(PUBLIC_DATA.glob("0*.csv")):
        if path.name == exclude:
            continue
        content = path.read_bytes()
        if replacement and path.name == replacement[0]:
            content = replacement[1]
        payloads.append(("files", (path.name, content, "text/csv")))
    return payloads


def candidate_schedule(scenario: Scenario) -> ScenarioSchedule:
    return ScenarioSchedule(
        scenario=scenario,
        access_assignments=[AccessAssignment(activity_id="A001", access_seq=1, week=1, eclo=0, access_night=1)],
        occupancy_assignments=[OccupancyAssignment(activity_id="A001", week=1, location_id="SEC:ALP:S01_S02:EB", co_share_group="b1")],
        contract_results=[ContractResult(scenario=scenario, contract_number="C001", simulated_completion_date=date(2027, 1, 10), overrun_days=0)],
    )


class CleanSolver:
    def __init__(self) -> None:
        self.changes: list[ScenarioChange | None] = []
        self.prepared_instances: list[PreparedInstance] = []

    def solve(self, prepared_instance, scenario, scenario_change=None) -> SolverOutput:
        self.prepared_instances.append(prepared_instance)
        self.changes.append(scenario_change)
        schedule = load_submission(CLEAN_SCENARIO_A)
        assert schedule.scenario is scenario
        return SolverOutput(schedule=schedule)


class InvalidScheduleSolver:
    def solve(self, prepared_instance, scenario, scenario_change=None) -> SolverOutput:
        return SolverOutput(schedule=candidate_schedule(scenario))


class FailingSolver:
    def solve(self, prepared_instance, scenario, scenario_change=None) -> SolverOutput:
        raise RuntimeError("test solver failure")


def set_run_service(solver=None) -> RunService:
    previous = getattr(app.state, "run_service", None)
    if previous:
        previous.store.clear()
    service = RunService(solver=solver)
    app.state.run_service = service
    return service


def create_public_run(client: TestClient) -> str:
    response = client.post("/api/v1/runs", data={"scenario": "A"}, files=public_files())
    assert response.status_code == 202
    return response.json()["run_id"]


def test_v1_health_and_request_id() -> None:
    response = TestClient(app).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["api_version"] == "v1"
    assert response.json()["validator_status"] == "unavailable"
    assert response.headers["x-request-id"]


def test_valid_upload_creates_a_blocked_run_without_solver() -> None:
    set_run_service()
    client = TestClient(app)

    run_id = create_public_run(client)
    response = client.get(f"/api/v1/runs/{run_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["problem"]["code"] == "solver_unavailable"
    assert body["validation_report"]["status"] == "unavailable"
    assert body["validation_report"]["feasible"] is None
    assert body["input_instance"]["row_counts"]["activities"] == 54


def test_upload_rejects_missing_and_schema_invalid_files() -> None:
    set_run_service()
    client = TestClient(app)

    missing = client.post("/api/v1/runs", data={"scenario": "A"}, files=public_files(exclude="08_ACTIVITY_DETAILS.csv"))
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "invalid_input_package"
    assert "08_ACTIVITY_DETAILS.csv" in str(missing.json()["error"]["field_errors"])

    invalid = client.post(
        "/api/v1/runs",
        data={"scenario": "A"},
        files=public_files(replacement=("01_LINES.csv", b"line_code,line_name,extra\nALP,Line Alpha,x\n")),
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "input_schema_invalid"


def test_upload_rejects_duplicate_and_unexpected_filenames() -> None:
    set_run_service()
    client = TestClient(app)
    files = public_files()
    files.append(("files", ("01_LINES.csv", (PUBLIC_DATA / "01_LINES.csv").read_bytes(), "text/csv")))
    duplicate = client.post("/api/v1/runs", data={"scenario": "A"}, files=files)
    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["code"] == "invalid_input_package"
    assert "duplicate filename" in str(duplicate.json()["error"]["field_errors"])

    unexpected_files = public_files()
    unexpected_files[-1] = ("files", ("unexpected.csv", b"a,b\n1,2\n", "text/csv"))
    unexpected = client.post("/api/v1/runs", data={"scenario": "A"}, files=unexpected_files)
    assert unexpected.status_code == 422
    assert unexpected.json()["error"]["code"] == "invalid_input_package"


def test_unknown_and_blocked_exports_return_actionable_errors() -> None:
    set_run_service()
    client = TestClient(app)

    unknown = client.get("/api/v1/runs/not-a-run")
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "run_not_found"

    run_id = create_public_run(client)
    blocked = client.get(f"/api/v1/runs/{run_id}/exports/SCHEDULE_ACCESS.csv")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "export_unavailable"


def test_clean_candidate_exports_but_keeps_it_unverified() -> None:
    solver = CleanSolver()
    set_run_service(solver)
    client = TestClient(app)

    run_id = create_public_run(client)
    result = client.get(f"/api/v1/runs/{run_id}")
    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "succeeded"
    assert body["schedule"]["scenario"] == "A"
    assert body["validation_report"]["status"] == "unverified"
    assert body["validation_report"]["feasible"] is None
    assert body["validation_report"]["hard_violations"] == []
    assert isinstance(solver.prepared_instances[0], PreparedInstance)

    export = client.get(f"/api/v1/runs/{run_id}/exports/SCHEDULE_ACCESS.csv")
    assert export.status_code == 200
    assert export.text.startswith("activity_id,access_seq,week,eclo,access_night\n")


def test_invalid_candidate_fails_preflight_retains_evidence_and_blocks_exports() -> None:
    set_run_service(InvalidScheduleSolver())
    client = TestClient(app)

    run_id = create_public_run(client)
    result = client.get(f"/api/v1/runs/{run_id}")

    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "failed"
    assert body["problem"]["code"] == "preflight_failed"
    assert body["schedule"] is not None
    report = body["validation_report"]
    assert report["status"] == "unverified"
    assert report["feasible"] is None
    assert report["hard_violations"]
    assert any(item["activity_ids"] for item in report["hard_violations"])
    assert any(
        item["location_ids"] and item["week"]
        for item in report["hard_violations"]
    )
    topology = next(item for item in report["hard_violations"] if item["rule"] == "topology")
    assert topology["derived_footprint"]
    assert topology["input_values"]["missing_location_count"] > 0

    export = client.get(f"/api/v1/runs/{run_id}/exports/SCHEDULE_ACCESS.csv")
    assert export.status_code == 409
    assert export.json()["error"]["code"] == "preflight_not_clean"


def test_unimplemented_scenario_b_is_blocked_not_silently_solved_as_a() -> None:
    set_run_service(CpSatSolverAdapter(time_limit_seconds=1))
    client = TestClient(app)

    response = client.post("/api/v1/runs", data={"scenario": "B"}, files=public_files())
    assert response.status_code == 202
    result = client.get(f"/api/v1/runs/{response.json()['run_id']}")

    assert result.status_code == 200
    assert result.json()["status"] == "blocked"
    assert result.json()["problem"]["code"] == "scenario_unavailable"


def test_scenario_c_is_supported_and_never_falls_back_to_scenario_a() -> None:
    set_run_service(CpSatSolverAdapter(time_limit_seconds=1))
    client = TestClient(app)

    response = client.post("/api/v1/runs", data={"scenario": "C"}, files=public_files())
    assert response.status_code == 202
    result = client.get(f"/api/v1/runs/{response.json()['run_id']}")

    assert result.status_code == 200
    assert result.json()["status"] != "blocked"
    assert result.json().get("problem", {}).get("code") != "scenario_unavailable"


def test_solver_preprocessing_failure_is_reported_without_falling_back() -> None:
    invalid_activity_csv = (PUBLIC_DATA / "08_ACTIVITY_DETAILS.csv").read_text(encoding="utf-8")
    invalid_activity_csv = invalid_activity_csv.replace("A001,C001,Renewal", "A001,UNKNOWN,Renewal", 1)
    set_run_service(CpSatSolverAdapter(time_limit_seconds=1))
    client = TestClient(app)

    response = client.post(
        "/api/v1/runs",
        data={"scenario": "A"},
        files=public_files(replacement=("08_ACTIVITY_DETAILS.csv", invalid_activity_csv.encode("utf-8"))),
    )
    assert response.status_code == 202
    result = client.get(f"/api/v1/runs/{response.json()['run_id']}")

    assert result.status_code == 200
    assert result.json()["status"] == "failed"
    assert result.json()["problem"]["code"] == "solver_input_invalid"
    finding = result.json()["validation_report"]["hard_violations"][0]
    assert finding["source_file"] == "08_ACTIVITY_DETAILS.csv"
    assert finding["row"] == 2
    assert finding["field"] == "contract_number"


def test_real_scenario_a_solver_produces_clean_unverified_exports() -> None:
    set_run_service(CpSatSolverAdapter(time_limit_seconds=30))
    client = TestClient(app)

    run_id = create_public_run(client)
    result = client.get(f"/api/v1/runs/{run_id}")

    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "succeeded"
    assert body["schedule"]["scenario"] == "A"
    assert body["validation_report"]["status"] == "unverified"
    assert body["validation_report"]["feasible"] is None
    assert body["validation_report"]["hard_violations"] == []
    for filename in ("SCHEDULE_ACCESS.csv", "SCHEDULE_OCCUPANCY.csv", "RESULTS.csv"):
        assert client.get(f"/api/v1/runs/{run_id}/exports/{filename}").status_code == 200


def test_solver_failure_is_a_failed_run() -> None:
    set_run_service(FailingSolver())
    client = TestClient(app)

    run_id = create_public_run(client)
    result = client.get(f"/api/v1/runs/{run_id}")

    assert result.status_code == 200
    assert result.json()["status"] == "failed"
    assert result.json()["problem"]["code"] == "solver_failed"


def test_cleared_in_memory_run_is_not_retrievable() -> None:
    service = set_run_service()
    client = TestClient(app)
    run_id = create_public_run(client)
    service.store.clear()

    response = client.get(f"/api/v1/runs/{run_id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "run_not_found"


def test_unverified_report_cannot_claim_feasibility() -> None:
    with pytest.raises(ValueError, match="only verified reports"):
        ValidationReport(
            status=ValidationStatus.UNVERIFIED,
            feasible=True,
            message="local check",
        )


def test_recovery_requires_confirmation_and_preserves_change_for_adapter() -> None:
    solver = CleanSolver()
    set_run_service(solver)
    client = TestClient(app)
    base_run_id = create_public_run(client)
    base = client.get(f"/api/v1/runs/{base_run_id}").json()
    schedule_id = base["schedule"]["schedule_id"]

    draft = {
        "change_id": "draft-1",
        "base_schedule_id": schedule_id,
        "scenario": "A",
        "requested_by": "controller",
    }
    unconfirmed = client.post(f"/api/v1/runs/{base_run_id}/recovery", json=draft)
    assert unconfirmed.status_code == 422
    assert unconfirmed.json()["error"]["code"] == "scenario_change_unconfirmed"

    confirmed = {
        **draft,
        "change_id": "confirmed-1",
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
        "locked_placements": [{"activity_id": "A001", "access_seq": 1}],
        "supply_overrides": [{"location_id": "SEC:ALP:S01_S02:EB", "week": 1, "supply_capacity": 1}],
    }
    recovery = client.post(f"/api/v1/runs/{base_run_id}/recovery", json=confirmed)
    assert recovery.status_code == 202
    recovery_id = recovery.json()["run_id"]
    recovered = client.get(f"/api/v1/runs/{recovery_id}").json()
    assert recovered["status"] == "succeeded"
    assert solver.changes[-1] is not None
    assert solver.changes[-1].locked_placements[0].activity_id == "A001"
