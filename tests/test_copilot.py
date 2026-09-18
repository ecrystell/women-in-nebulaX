"""Read-only Gemini copilot regression and hidden-data boundary coverage."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.ai.gemini import CopilotService
from app.api.run_service import RunService, SolverOutput, utc_now
from app.domain.models import Scenario
from app.main import app
from app.validation.preflight import load_submission


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DATA = ROOT / "data" / "public-instance"
SAMPLE_SUBMISSION = PUBLIC_DATA / "sample-submission"


def public_files() -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (path.name, path.read_bytes(), "text/csv")) for path in sorted(PUBLIC_DATA.glob("0*.csv"))]


class CleanSolver:
    def solve(self, prepared_instance, scenario, scenario_change=None) -> SolverOutput:
        schedule = load_submission(SAMPLE_SUBMISSION)
        assert scenario is Scenario.A
        return SolverOutput(schedule=schedule)


class CapturingGenerator:
    model_name = "test-gemini"

    def __init__(self, *, answer: str = "The evidence shows the requested local schedule facts.") -> None:
        self.answer = answer
        self.payloads: list[dict[str, object]] = []

    def generate(self, evidence, mode) -> str:
        self.payloads.append(evidence.model_dump(mode="json"))
        return json.dumps({"answer": self.answer, "schedule_id": evidence.schedule_id})


def set_services(generator: CapturingGenerator | None = None) -> tuple[RunService, CapturingGenerator]:
    previous = getattr(app.state, "run_service", None)
    if previous:
        previous.store.clear()
    service = RunService(solver=CleanSolver())
    actual_generator = generator or CapturingGenerator()
    app.state.run_service = service
    app.state.copilot_service = CopilotService(actual_generator)
    return service, actual_generator


def create_run(client: TestClient) -> str:
    response = client.post("/api/v1/runs", data={"scenario": "A"}, files=public_files())
    assert response.status_code == 202, response.text
    assert "httponly" in response.headers["set-cookie"].lower()
    return response.json()["run_id"]


def test_evidence_routes_are_deterministic_and_minimised() -> None:
    _, generator = set_services()
    client = TestClient(app)
    run_id = create_run(client)

    activity = client.get(f"/api/v1/runs/{run_id}/evidence/activities/A001")
    assert activity.status_code == 200
    body = activity.json()
    assert body["evidence_version"] == "1"
    assert body["validation"]["status"] == "unverified"
    assert body["validation"]["feasible"] is None
    assert body["payload"]["kind"] == "activity"
    assert body["payload"]["activity_id"] == "A001"
    assert body["payload"]["placements"]
    assert body["payload"]["closure_footprint"]

    hotspots = client.get(f"/api/v1/runs/{run_id}/evidence/capacity-hotspots")
    assert hotspots.status_code == 200
    entries = hotspots.json()["payload"]["hotspots"]
    assert len(entries) <= 10
    assert entries == sorted(entries, key=lambda item: (-item["excess_access_nights"], -item["utilisation"], item["location_id"], item["week"]))

    handover = client.get(f"/api/v1/runs/{run_id}/evidence/handover")
    assert handover.status_code == 200
    assert handover.json()["payload"]["kind"] == "handover"

    response = client.post(
        f"/api/v1/runs/{run_id}/copilot-responses",
        json={"mode": "activity_explanation", "activity_id": "A001"},
    )
    assert response.status_code == 200
    assert response.json()["verification_disclaimer"].startswith("Organiser verification")
    assert generator.payloads
    transmitted = json.dumps(generator.payloads[-1])
    assert "01_LINES.csv" not in transmitted
    assert "SCHEDULE_ACCESS.csv" not in transmitted
    assert "submission_manifest" not in transmitted
    assert '"activities"' not in transmitted
    assert generator.payloads[-1]["payload"]["activity_id"] == "A001"


def test_copilot_never_falls_back_or_accepts_unsafe_model_text() -> None:
    _, generator = set_services(CapturingGenerator(answer="This schedule is feasible and safe to operate."))
    client = TestClient(app)
    run_id = create_run(client)
    unsafe = client.post(f"/api/v1/runs/{run_id}/copilot-responses", json={"mode": "handover_summary"})
    assert unsafe.status_code == 503
    assert unsafe.json()["error"]["code"] == "copilot_unavailable"
    assert generator.payloads


def test_copilot_route_requires_schedule_cookie_and_expires(monkeypatch) -> None:
    service, _ = set_services()
    owner = TestClient(app)
    run_id = create_run(owner)
    stranger = TestClient(app)
    denied = stranger.get(f"/api/v1/runs/{run_id}/evidence/handover")
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "run_not_found"

    monkeypatch.setenv("RAILACCESS_RUN_TTL_SECONDS", "60")
    record = service.store.get(run_id)
    assert record is not None
    record.last_accessed_at = utc_now() - timedelta(seconds=61)
    expired = owner.get(f"/api/v1/runs/{run_id}")
    assert expired.status_code == 404
    assert service.store.get(run_id) is None


def test_copilot_rejects_bad_activity_and_enforces_rate_limit() -> None:
    _, _ = set_services()
    client = TestClient(app)
    run_id = create_run(client)
    bad_activity = client.get(f"/api/v1/runs/{run_id}/evidence/activities/UNKNOWN")
    assert bad_activity.status_code == 404
    assert bad_activity.json()["error"]["code"] == "activity_not_found"

    for _ in range(10):
        response = client.post(f"/api/v1/runs/{run_id}/copilot-responses", json={"mode": "capacity_hotspots"})
        assert response.status_code == 200
    limited = client.post(f"/api/v1/runs/{run_id}/copilot-responses", json={"mode": "capacity_hotspots"})
    assert limited.status_code == 503
    assert limited.json()["error"]["code"] == "copilot_unavailable"
