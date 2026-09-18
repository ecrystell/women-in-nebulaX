"""Consistent HTTP error responses for the versioned API."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from app.api.schemas import ApiError, ApiErrorResponse, ApiFieldError


class ApiException(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        field_errors: list[ApiFieldError] | None = None,
    ) -> None:
        self.status_code = status_code
        self.payload = ApiError(code=code, message=message, field_errors=field_errors or [])


def error_response(request: Request, status_code: int, payload: ApiError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    body = ApiErrorResponse(request_id=request_id, error=payload)
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers={"X-Request-ID": request_id},
    )
