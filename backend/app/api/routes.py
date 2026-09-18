"""`/api/v1` routes for uploads, run status, exports, and recovery."""

from __future__ import annotations

import hashlib
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.errors import ApiException
from app.api.run_service import RunService, SubmissionPackageError
from app.api.schemas import (
    ApiFieldError,
    InputInstance,
    InputSource,
    OrganiserEvidenceInput,
    RunView,
    ScenarioChange,
    SubmissionPackageSummary,
)
from app.domain.models import Scenario
from app.ingestion.csv_loader import INPUT_TABLES, InstanceLoadError, load_instance

router = APIRouter(prefix="/api/v1", tags=["v1"])
ALLOWED_EXPORTS = frozenset({"SCHEDULE_ACCESS.csv", "SCHEDULE_OCCUPANCY.csv", "RESULTS.csv"})


def get_service(request: Request) -> RunService:
    return request.app.state.run_service


def _field_errors_for_filenames(filenames: list[str]) -> list[ApiFieldError]:
    expected = set(INPUT_TABLES)
    seen: set[str] = set()
    errors: list[ApiFieldError] = []
    for filename in filenames:
        if filename in seen:
            errors.append(ApiFieldError(field="files", message=f"duplicate filename: {filename}"))
        seen.add(filename)
        if filename not in expected:
            errors.append(ApiFieldError(field="files", message=f"unexpected filename: {filename}"))
    for filename in sorted(expected - set(filenames)):
        errors.append(ApiFieldError(field="files", message=f"missing filename: {filename}"))
    return errors


async def parse_uploaded_instance(files: list[UploadFile]) -> InputInstance:
    filenames = [upload.filename or "" for upload in files]
    errors = _field_errors_for_filenames(filenames)
    if errors:
        raise ApiException(422, "invalid_input_package", "Expected exactly the eight official CSV filenames.", errors)

    with tempfile.TemporaryDirectory(prefix="railaccess-upload-") as temp_dir:
        directory = Path(temp_dir)
        file_checksums: dict[str, str] = {}
        for upload in files:
            filename = upload.filename or ""
            if Path(filename).name != filename:
                raise ApiException(
                    422,
                    "invalid_input_package",
                    "CSV filenames must not include a directory path.",
                    [ApiFieldError(field="files", message=f"invalid filename: {filename}")],
                )
            contents = await upload.read()
            file_checksums[filename] = hashlib.sha256(contents).hexdigest()
            (directory / filename).write_bytes(contents)
        try:
            bundle = load_instance(directory)
        except (InstanceLoadError, UnicodeDecodeError) as error:
            raise ApiException(
                422,
                "input_schema_invalid",
                "The uploaded CSV package does not match the official input schema.",
                [ApiFieldError(field="files", message=str(error))],
            ) from error

    return InputInstance.from_bundle(
        bundle,
        InputSource(
            instance_id=str(uuid4()),
            received_at=datetime.now(timezone.utc),
            fixture=False,
            file_checksums=file_checksums,
        ),
    )


@router.get("/health")
def health(request: Request) -> dict[str, object]:
    service = get_service(request)
    return {
        "service": "railaccess-ai",
        "api_version": "v1",
        "status": "ok",
        "validator_status": service.validator.status().status.value,
    }


@router.post("/runs", response_model=RunView, status_code=202)
async def create_run(
    request: Request,
    background_tasks: BackgroundTasks,
    scenario: Scenario = Form(...),
    files: list[UploadFile] = File(...),
) -> RunView:
    service = get_service(request)
    instance = await parse_uploaded_instance(files)
    record = service.create_run(instance, scenario)
    background_tasks.add_task(service.dispatch, record.run_id)
    return record.to_view()


@router.get("/runs/{run_id}", response_model=RunView)
def get_run(request: Request, run_id: str) -> RunView:
    view = get_service(request).get_view(run_id)
    if view is None:
        raise ApiException(404, "run_not_found", f"No run exists with id {run_id}.")
    return view


@router.get("/runs/{run_id}/exports/{filename}")
def download_export(request: Request, run_id: str, filename: str) -> FileResponse:
    if filename not in ALLOWED_EXPORTS:
        raise ApiException(404, "export_not_found", "The requested export filename is not supported.")
    service = get_service(request)
    view = service.get_view(run_id)
    if view is None:
        raise ApiException(404, "run_not_found", f"No run exists with id {run_id}.")
    path = service.get_export(run_id, filename)
    if path is None:
        if view.problem is not None and view.problem.code == "preflight_failed":
            raise ApiException(
                409,
                "preflight_not_clean",
                "Local preflight found hard violations; submission exports are unavailable.",
            )
        raise ApiException(
            409,
            "export_unavailable",
            "Exports are available only after a candidate schedule succeeds.",
        )
    return FileResponse(path, media_type="text/csv", filename=filename)


def _submission_exception(error: SubmissionPackageError) -> ApiException:
    if error.code in {"run_not_found", "submission_package_not_found"}:
        status = 404
    elif error.code == "submission_package_failed":
        status = 500
    else:
        status = 409
    return ApiException(status, error.code, str(error))


@router.post("/runs/{run_id}/submission-packages", response_model=SubmissionPackageSummary, status_code=201)
def create_submission_package(request: Request, run_id: str) -> SubmissionPackageSummary:
    try:
        return get_service(request).create_submission_package(run_id).to_summary()
    except SubmissionPackageError as error:
        raise _submission_exception(error) from error


@router.get("/runs/{run_id}/submission-packages/{package_id}/download")
def download_submission_package(request: Request, run_id: str, package_id: str) -> FileResponse:
    try:
        package = get_service(request).get_submission_package(run_id, package_id)
    except SubmissionPackageError as error:
        raise _submission_exception(error) from error
    if not package.bundle_path.is_file():
        raise ApiException(409, "submission_package_unavailable", "The submission package is no longer available.")
    return FileResponse(
        package.bundle_path,
        media_type="application/zip",
        filename=f"railaccess-submission-{package_id}.zip",
    )


@router.post(
    "/runs/{run_id}/submission-packages/{package_id}/organiser-evidence",
    response_model=SubmissionPackageSummary,
)
def record_organiser_evidence(
    request: Request,
    run_id: str,
    package_id: str,
    payload: OrganiserEvidenceInput,
) -> SubmissionPackageSummary:
    try:
        return get_service(request).record_organiser_evidence(run_id, package_id, payload).to_summary()
    except SubmissionPackageError as error:
        raise _submission_exception(error) from error


@router.get("/runs/{run_id}/submission-packages/{package_id}/evidence-record")
def download_evidence_record(request: Request, run_id: str, package_id: str) -> FileResponse:
    try:
        path = get_service(request).get_evidence_record(run_id, package_id)
    except SubmissionPackageError as error:
        raise _submission_exception(error) from error
    return FileResponse(path, media_type="application/json", filename=f"railaccess-evidence-{package_id}.json")


@router.post("/runs/{run_id}/recovery", response_model=RunView, status_code=202)
def create_recovery(
    request: Request,
    run_id: str,
    change: ScenarioChange,
    background_tasks: BackgroundTasks,
) -> RunView:
    if change.confirmed_at is None:
        raise ApiException(
            422,
            "scenario_change_unconfirmed",
            "A recovery request must include an explicit confirmation timestamp.",
            [ApiFieldError(field="confirmed_at", message="confirmation is required")],
        )
    service = get_service(request)
    base = service.get_view(run_id)
    if base is None:
        raise ApiException(404, "run_not_found", f"No run exists with id {run_id}.")
    if base.status.value != "succeeded" or base.schedule is None:
        raise ApiException(
            409,
            "recovery_unavailable",
            "Recovery requires a run with a candidate schedule.",
        )
    if change.base_schedule_id != base.schedule.schedule_id or change.scenario != base.scenario:
        raise ApiException(
            422,
            "scenario_change_invalid",
            "The recovery request must reference the base run's candidate schedule and scenario.",
        )
    record = service.create_recovery(run_id, change)
    if record is None:
        raise ApiException(409, "recovery_unavailable", "Recovery is unavailable for this run.")
    background_tasks.add_task(service.dispatch, record.run_id)
    return record.to_view()
