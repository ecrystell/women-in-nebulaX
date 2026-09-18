"""FastAPI application and production static frontend host."""

from __future__ import annotations

import os
from pathlib import Path

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.errors import ApiException, error_response
from app.api.routes import router as v1_router
from app.api.run_service import RunService
from app.api.schemas import ApiError, ApiFieldError
from app.validation.adapter import OfficialValidatorAdapter

app = FastAPI(title="RailAccess AI", version="0.1.0")
validator = OfficialValidatorAdapter()
app.state.run_service = RunService(validator=validator)


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(ApiException)
async def api_exception_handler(request: Request, error: ApiException) -> JSONResponse:
    return error_response(request, error.status_code, error.payload)


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    field_errors = [
        ApiFieldError(field=".".join(str(part) for part in issue["loc"]), message=issue["msg"])
        for issue in error.errors()
    ]
    return error_response(
        request,
        422,
        ApiError(code="request_validation_error", message="The request is invalid.", field_errors=field_errors),
    )


app.include_router(v1_router)


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
