from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.ai.disruption_drafts import DisruptionDraftService, VertexDraftGenerator
from app.api.run_service import RunService
from app.main import app
from app.solver.adapter import CpSatSolverAdapter


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DATA = ROOT / "data" / "public-instance"


class StubDraftGenerator:
    available = True

    def __init__(self, payload: dict[str, object] | str) -> None:
        self.payload = payload
        self.context: dict[str, object] | None = None

    def generate(self, context: dict[str, object]) -> str:
        self.context = context
        return self.payload if isinstance(self.payload, str) else json.dumps(self.payload)


def test_vertex_json_extraction_ignores_thoughts_and_markdown_fences() -> None:
    class Part:
        def __init__(self, text: str, *, thought: bool = False) -> None:
            self.text = text
            self.thought = thought

    class Candidate:
        class Content:
            parts = [Part("internal reasoning", thought=True), Part("```json\n{\"supply_overrides\":[]}\n```")]

        content = Content()

    class Response:
        candidates = [Candidate()]
        text = "not the final JSON boundary"

    assert VertexDraftGenerator._final_json_text(Response()) == '{"supply_overrides":[]}'


def set_services(generator: StubDraftGenerator) -> None:
    previous = getattr(app.state, "run_service", None)
    if previous:
        previous.store.clear()
    app.state.run_service = RunService(solver=CpSatSolverAdapter(time_limit_seconds=1))
    app.state.disruption_draft_service = DisruptionDraftService(generator)


def public_files() -> list[tuple[str, tuple[str, bytes, str]]]:
    return [
        ("files", (path.name, path.read_bytes(), "text/csv"))
        for path in sorted(PUBLIC_DATA.glob("0*.csv"))
    ]


def ready_payload() -> dict[str, object]:
    return {
        "supply_overrides": [
            {"location_id": "SEC:ALP:S01_S02:EB", "week": 22, "supply_capacity": 2}
        ],
        "locked_placements": [{"activity_id": "A001", "access_seq": 1}],
        "rationale": "Controller review required before the fixed public replay.",
        "assumptions": ["The request refers to the public fixture."],
        "unresolved_references": [],
    }


def create_demo(client: TestClient) -> dict[str, object]:
    response = client.post("/api/v1/demo-runs")
    assert response.status_code == 201, response.text
    return response.json()


def test_capabilities_and_public_demo_are_explicitly_separate_from_live_runs() -> None:
    generator = StubDraftGenerator(ready_payload())
    set_services(generator)
    client = TestClient(app)

    capabilities = client.get("/api/v1/capabilities")
    assert capabilities.status_code == 200
    body = capabilities.json()
    scenarios = {item["scenario"]: item for item in body["scenarios"]}
    assert scenarios["A"]["available"] is True
    assert scenarios["B"] == {
        "scenario": "B",
        "available": False,
        "code": "scenario_unavailable",
        "message": scenarios["B"]["message"],
    }
    assert scenarios["C"]["available"] is False
    assert body["recovery"]["code"] == "recovery_solver_unavailable"
    assert body["public_demo_recovery"]["available"] is True
    assert body["disruption_drafts"]["available"] is True

    demo = create_demo(client)
    assert demo["demo"] is True
    assert demo["input_instance"]["fixture"] is True
    assert demo["status"] == "succeeded"
    assert demo["validation_report"]["status"] == "unverified"
    assert demo["validation_report"]["feasible"] is None
    assert demo["validation_report"]["hard_violations"] == []
    assert "not a newly optimised schedule" in demo["demo_notice"]
    assert demo["scenario_change"]["supply_overrides"]
    assert demo["scenario_change"]["locked_placements"]

    run_id = demo["run_id"]
    export = client.get(f"/api/v1/runs/{run_id}/exports/SCHEDULE_ACCESS.csv")
    assert export.status_code == 409
    package = client.post(f"/api/v1/runs/{run_id}/submission-packages")
    assert package.status_code == 409
    assert package.json()["error"]["code"] == "demo_submission_unavailable"

    replay = client.post(f"/api/v1/runs/{run_id}/demo-recovery")
    assert replay.status_code == 201, replay.text
    replay_body = replay.json()
    assert replay_body["demo"] is True
    assert replay_body["recovery_of_run_id"] == run_id
    assert replay_body["validation_report"]["status"] == "unverified"
    assert replay_body["schedule_diff"]["moved_count"] == 0
    assert replay_body["schedule_diff"]["unchanged_count"] > 0
    assert replay_body["scenario_change"]["locked_placements"]


def test_draft_parser_is_public_only_bounded_and_requires_a_ready_draft_for_confirmation() -> None:
    generator = StubDraftGenerator(ready_payload())
    set_services(generator)
    client = TestClient(app)
    demo = create_demo(client)
    run_id = demo["run_id"]

    draft_response = client.post(
        f"/api/v1/runs/{run_id}/disruption-drafts",
        json={"text": "Reduce ALP S01 to S02 in week 22 and lock A001 access 1."},
    )
    assert draft_response.status_code == 200, draft_response.text
    draft = draft_response.json()
    assert draft["status"] == "ready"
    assert draft["change"]["confirmed_at"] is None
    assert generator.context is not None
    assert set(generator.context) == {
        "request",
        "scenario",
        "schedule_id",
        "horizon_weeks",
        "valid_supply_locations",
        "valid_placement_keys",
    }
    transmitted = json.dumps(generator.context)
    assert "SCHEDULE_ACCESS.csv" not in transmitted
    assert "checksum" not in transmitted.lower()
    assert "organiser" not in transmitted.lower()

    confirmed = client.post(
        f"/api/v1/runs/{run_id}/demo-recovery", json={"draft_id": draft["draft_id"]}
    )
    assert confirmed.status_code == 201, confirmed.text

    bad_generator = StubDraftGenerator(
        {
            **ready_payload(),
            "supply_overrides": [
                {"location_id": "SEC:UNKNOWN:S01_S02:EB", "week": 999, "supply_capacity": 1}
            ],
        }
    )
    app.state.disruption_draft_service = DisruptionDraftService(bad_generator)
    unresolved = client.post(
        f"/api/v1/runs/{run_id}/disruption-drafts", json={"text": "Use an unknown location."}
    )
    assert unresolved.status_code == 200
    unresolved_body = unresolved.json()
    assert unresolved_body["status"] == "needs_review"
    assert unresolved_body["field_errors"]
    rejected_confirmation = client.post(
        f"/api/v1/runs/{run_id}/demo-recovery", json={"draft_id": unresolved_body["draft_id"]}
    )
    assert rejected_confirmation.status_code == 422
    assert rejected_confirmation.json()["error"]["code"] == "disruption_draft_not_ready"


def test_draft_parser_rejects_live_uploads_and_unsafe_or_invalid_model_output() -> None:
    generator = StubDraftGenerator(ready_payload())
    set_services(generator)
    client = TestClient(app)

    live = client.post("/api/v1/runs", data={"scenario": "A"}, files=public_files())
    assert live.status_code == 202
    forbidden_live = client.post(
        f"/api/v1/runs/{live.json()['run_id']}/disruption-drafts", json={"text": "reduce supply"}
    )
    assert forbidden_live.status_code == 409
    assert forbidden_live.json()["error"]["code"] == "public_demo_only"

    real_recovery = client.post(
        f"/api/v1/runs/{live.json()['run_id']}/recovery",
        json={
            "change_id": "confirmed-but-unavailable",
            "base_schedule_id": "not-used-while-recovery-is-unavailable",
            "scenario": "A",
            "requested_by": "controller",
            "confirmed_at": "2026-09-19T00:00:00Z",
        },
    )
    assert real_recovery.status_code == 409
    assert real_recovery.json()["error"]["code"] == "recovery_solver_unavailable"

    demo = create_demo(client)
    unsafe = StubDraftGenerator({**ready_payload(), "rationale": "This schedule is feasible."})
    app.state.disruption_draft_service = DisruptionDraftService(unsafe)
    unsafe_response = client.post(
        f"/api/v1/runs/{demo['run_id']}/disruption-drafts", json={"text": "reduce supply"}
    )
    assert unsafe_response.status_code == 503
    assert unsafe_response.json()["error"]["code"] == "disruption_parser_unavailable"

    malformed = StubDraftGenerator("not-json")
    app.state.disruption_draft_service = DisruptionDraftService(malformed)
    malformed_response = client.post(
        f"/api/v1/runs/{demo['run_id']}/disruption-drafts", json={"text": "reduce supply"}
    )
    assert malformed_response.status_code == 503
    assert malformed_response.json()["error"]["code"] == "disruption_parser_unavailable"


def test_supply_csv_creates_editable_all_week_draft_for_a_live_run() -> None:
    set_services(StubDraftGenerator(ready_payload()))
    client = TestClient(app)
    live = client.post("/api/v1/runs", data={"scenario": "A"}, files=public_files())
    assert live.status_code == 202
    run_id = live.json()["run_id"]
    for _ in range(30):
        view = client.get(f"/api/v1/runs/{run_id}")
        assert view.status_code == 200
        if view.json()["status"] != "running":
            break
    assert view.json()["status"] == "succeeded"

    replacement = (PUBLIC_DATA / "04_LOCATION_SUPPLY.csv").read_text(encoding="utf-8")
    replacement = replacement.replace("SEC:ALP:S01_S02:EB,tunnel sector,ALP,EB,4", "SEC:ALP:S01_S02:EB,tunnel sector,ALP,EB,2")
    created = client.post(
        f"/api/v1/runs/{run_id}/recovery-drafts/supply-csv",
        files={"file": ("04_LOCATION_SUPPLY.csv", replacement.encode(), "text/csv")},
    )
    assert created.status_code == 200, created.text
    draft = created.json()
    assert draft["source"] == "supply_csv"
    assert draft["status"] == "ready"
    # The public fixture currently has a 30-week horizon; every horizon week is present.
    assert {item["week"] for item in draft["change"]["supply_overrides"]} == set(range(1, 31))

    edited = client.patch(
        f"/api/v1/runs/{run_id}/recovery-drafts/{draft['draft_id']}",
        json={
            "supply_overrides": [{"location_id": "SEC:ALP:S01_S02:EB", "week": 5, "supply_capacity": 1}],
            "locked_placements": [{"activity_id": view.json()["schedule"]["placements"][0]["activity_id"], "access_seq": view.json()["schedule"]["placements"][0]["access_seq"]}],
            "rationale": "Controller narrowed the disruption.",
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["source"] == "manual_review"
    assert edited.json()["change"]["supply_overrides"][0]["week"] == 5
    confirmation = client.post(f"/api/v1/runs/{run_id}/recovery-drafts/{edited.json()['draft_id']}/confirm")
    assert confirmation.status_code == 409
    assert confirmation.json()["error"]["code"] == "recovery_solver_unavailable"


def test_supply_csv_rejects_non_capacity_changes_and_noops() -> None:
    set_services(StubDraftGenerator(ready_payload()))
    client = TestClient(app)
    demo = create_demo(client)
    run_id = demo["run_id"]
    original = (PUBLIC_DATA / "04_LOCATION_SUPPLY.csv").read_bytes()
    noop = client.post(f"/api/v1/runs/{run_id}/recovery-drafts/supply-csv", files={"file": ("04_LOCATION_SUPPLY.csv", original, "text/csv")})
    assert noop.status_code == 422
    assert noop.json()["error"]["code"] == "recovery_supply_no_changes"
    altered = original.replace(b"tunnel sector,ALP,EB,4", b"platform sector,ALP,EB,4", 1)
    invalid = client.post(f"/api/v1/runs/{run_id}/recovery-drafts/supply-csv", files={"file": ("04_LOCATION_SUPPLY.csv", altered, "text/csv")})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_recovery_supply_csv"
