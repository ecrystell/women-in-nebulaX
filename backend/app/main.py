"""FastAPI application and production static frontend host."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.validation.adapter import OfficialValidatorAdapter

app = FastAPI(title="RailAccess AI", version="0.1.0")
validator = OfficialValidatorAdapter()


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "service": "railaccess-ai",
        "phase": "0",
        "status": "ok",
        "validator_status": validator.status().status.value,
    }


@app.get("/api/validation/status")
def validation_status() -> dict[str, object]:
    return validator.local_contract_check().model_dump(mode="json")


frontend_dist = Path(os.getenv("FRONTEND_DIST", Path(__file__).resolve().parents[1] / "frontend-dist"))
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
