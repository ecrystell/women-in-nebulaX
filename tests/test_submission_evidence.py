"""Regression coverage for manual organiser-upload evidence packages."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.run_service import RunService, SolverOutput
from app.domain.models import AccessAssignment, ContractResult, OccupancyAssignment, Scenario, ScenarioSchedule
from app.main import app
from app.validation.preflight import load_submission


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DATA = ROOT / "data" / "public-instance"
SAMPLE_SUBMISSION = PUBLIC_DATA / "sample-submission"
BUILD_COMMIT = "a" * 40


def public_files() -> list[tuple[str, tuple[str, bytes, str]]]:
    return [
        ("files", (path.name, path.read_bytes(), "text/csv"))
        for path in sorted(PUBLIC_DATA.glob("0*.csv"))
    ]


class CleanSolver:
    def solve(self, prepared_instance, scenario, scenario_change=None) -> SolverOutput:
        schedule = load_submission(SAMPLE_SUBMISSION)
        assert schedule.scenario is scenario
        return SolverOutput(schedule=schedule)


class InvalidSolver:
    def solve(self, prepared_instance, scenario, scenario_change=None) -> SolverOutput:
        return SolverOutput(
            schedule=ScenarioSchedule(
                scenario=scenario,
                access_assignments=[AccessAssignment(activity_id="A001", access_seq=1, week=1, eclo=0, access_night=1)],
                occupancy_assignments=[OccupancyAssignment(activity_id="A001", week=1, location_id="SEC:ALP:S01_S02:EB", co_share_group="b1")],
                contract_results=[ContractResult(scenario=scenario, contract_number="C001", simulated_completion_date=date(2027, 1, 10), overrun_days=0)],
            )
        )


def set_service(solver=None) -> RunService:
    previous = getattr(app.state, "run_service", None)
    if previous:
        previous.store.clear()
    service = RunService(solver=solver)
    app.state.run_service = service
    return service


def create_run(client: TestClient) -> str:
    response = client.post("/api/v1/runs", data={"scenario": "A"}, files=public_files())
    assert response.status_code == 202
    return response.json()["run_id"]


def create_package(client: TestClient, run_id: str) -> dict[str, object]:
    response = client.post(f"/api/v1/runs/{run_id}/submission-packages")
    assert response.status_code == 201, response.text
    return response.json()


def test_submission_bundle_manifest_and_evidence_record_are_reproducible(monkeypatch) -> None:
    monkeypatch.setenv("RAILACCESS_BUILD_COMMIT", BUILD_COMMIT)
    set_service(CleanSolver())
    client = TestClient(app)
    run_id = create_run(client)
    package = create_package(client, run_id)
    package_id = str(package["package_id"])

    bundle = client.get(f"/api/v1/runs/{run_id}/submission-packages/{package_id}/download")
    assert bundle.status_code == 200
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        assert set(archive.namelist()) == {
            "SCHEDULE_ACCESS.csv",
            "SCHEDULE_OCCUPANCY.csv",
            "RESULTS.csv",
            "submission-manifest.json",
        }
        manifest = json.loads(archive.read("submission-manifest.json"))
        assert manifest["build_commit"] == BUILD_COMMIT
        assert manifest["local_preflight_report"]["status"] == "unverified"
        assert manifest["local_preflight_report"]["feasible"] is None
        assert manifest["local_preflight_report"]["hard_violations"] == []
        for path in sorted(PUBLIC_DATA.glob("0*.csv")):
            assert manifest["input_checksums"][path.name] == hashlib.sha256(path.read_bytes()).hexdigest()
        for filename in ("SCHEDULE_ACCESS.csv", "SCHEDULE_OCCUPANCY.csv", "RESULTS.csv"):
            assert manifest["output_checksums"][filename] == hashlib.sha256(archive.read(filename)).hexdigest()

    no_evidence = client.get(f"/api/v1/runs/{run_id}/submission-packages/{package_id}/evidence-record")
    assert no_evidence.status_code == 409
    assert no_evidence.json()["error"]["code"] == "organiser_evidence_unavailable"

    evidence_payload = {
        "attempt_number": 1,
        "submitted_at": "2026-09-18T12:00:00Z",
        "reported_outcome": "accepted",
        "report_reference": "organiser-result-1.png",
        "report_sha256": "b" * 64,
        "note": "Recorded manually after the website response.",
    }
    recorded = client.post(
        f"/api/v1/runs/{run_id}/submission-packages/{package_id}/organiser-evidence",
        json=evidence_payload,
    )
    assert recorded.status_code == 200
    assert recorded.json()["organiser_evidence"]["reported_outcome"] == "accepted"
    view = client.get(f"/api/v1/runs/{run_id}").json()
    assert view["validation_report"]["status"] == "unverified"
    assert view["validation_report"]["feasible"] is None

    evidence = client.get(f"/api/v1/runs/{run_id}/submission-packages/{package_id}/evidence-record")
    assert evidence.status_code == 200
    evidence_record = evidence.json()
    assert evidence_record["submission_manifest"] == manifest
    assert evidence_record["organiser_evidence"]["attempt_number"] == 1


def test_submission_package_and_evidence_rejections_are_actionable(monkeypatch) -> None:
    monkeypatch.delenv("RAILACCESS_BUILD_COMMIT", raising=False)
    set_service(CleanSolver())
    client = TestClient(app)
    run_id = create_run(client)
    unknown = client.post("/api/v1/runs/not-a-run/submission-packages")
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "run_not_found"
    missing_commit = client.post(f"/api/v1/runs/{run_id}/submission-packages")
    assert missing_commit.status_code == 409
    assert missing_commit.json()["error"]["code"] == "submission_provenance_unavailable"

    monkeypatch.setenv("RAILACCESS_BUILD_COMMIT", BUILD_COMMIT)
    blocked_service = set_service()
    blocked_run = create_run(client)
    blocked = client.post(f"/api/v1/runs/{blocked_run}/submission-packages")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "submission_unavailable"

    set_service(InvalidSolver())
    invalid_run = create_run(client)
    preflight_invalid = client.post(f"/api/v1/runs/{invalid_run}/submission-packages")
    assert preflight_invalid.status_code == 409
    assert preflight_invalid.json()["error"]["code"] == "submission_unavailable"

    service = set_service(CleanSolver())
    run_id = create_run(client)
    first = create_package(client, run_id)
    first_id = str(first["package_id"])
    invalid_attempt = client.post(
        f"/api/v1/runs/{run_id}/submission-packages/{first_id}/organiser-evidence",
        json={"attempt_number": 0, "submitted_at": "2026-09-18T12:00:00Z", "reported_outcome": "unknown"},
    )
    assert invalid_attempt.status_code == 422
    sixth_attempt = client.post(
        f"/api/v1/runs/{run_id}/submission-packages/{first_id}/organiser-evidence",
        json={"attempt_number": 6, "submitted_at": "2026-09-18T12:00:00Z", "reported_outcome": "unknown"},
    )
    assert sixth_attempt.status_code == 422
    invalid_digest = client.post(
        f"/api/v1/runs/{run_id}/submission-packages/{first_id}/organiser-evidence",
        json={"attempt_number": 1, "submitted_at": "2026-09-18T12:00:00Z", "reported_outcome": "unknown", "report_sha256": "bad"},
    )
    assert invalid_digest.status_code == 422
    screenshot_upload = client.post(
        f"/api/v1/runs/{run_id}/submission-packages/{first_id}/organiser-evidence",
        json={"attempt_number": 1, "submitted_at": "2026-09-18T12:00:00Z", "reported_outcome": "unknown", "screenshot": "not accepted"},
    )
    assert screenshot_upload.status_code == 422
    accepted = client.post(
        f"/api/v1/runs/{run_id}/submission-packages/{first_id}/organiser-evidence",
        json={"attempt_number": 1, "submitted_at": "2026-09-18T12:00:00Z", "reported_outcome": "unknown"},
    )
    assert accepted.status_code == 200
    second = create_package(client, run_id)
    duplicate = client.post(
        f"/api/v1/runs/{run_id}/submission-packages/{second['package_id']}/organiser-evidence",
        json={"attempt_number": 1, "submitted_at": "2026-09-18T12:00:00Z", "reported_outcome": "rejected"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "organiser_attempt_duplicate"

    service.store.clear()
    expired = client.get(f"/api/v1/runs/{run_id}/submission-packages/{first_id}/download")
    assert expired.status_code == 404
