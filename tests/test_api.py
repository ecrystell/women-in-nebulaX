from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_unavailable_validator() -> None:
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "service": "for-rails",
        "phase": "0",
        "status": "ok",
        "validator_status": "unavailable",
    }


def test_validation_status_never_claims_feasibility() -> None:
    response = TestClient(app).get("/api/validation/status")

    assert response.status_code == 200
    assert response.json()["status"] == "unverified"
    assert response.json()["feasible"] is None
