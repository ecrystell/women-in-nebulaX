"""`/api/v1` routes for uploads, run status, exports, and recovery."""

from __future__ import annotations

import csv
import hashlib
import io
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app.api.errors import ApiException
from app.ai.gemini import CopilotService, CopilotUnavailable
from app.ai.disruption_drafts import DisruptionDraftService, DisruptionDraftUnavailable
from app.api.run_service import (
    PUBLIC_SUBMISSION_DIR,
    EvidenceUnavailable,
    RunRecord,
    RunService,
    SubmissionPackageError,
)
from app.api.schemas import (
    ApiFieldError,
    CapabilityReport,
    CopilotRequest,
    CopilotResponse,
    CopilotMode,
    DemoRecoveryRequest,
    EvidenceEnvelope,
    InputInstance,
    InputSource,
    OrganiserEvidenceInput,
    RunView,
    ScenarioChange,
    ScenarioChangeDraft,
    ScenarioChangeDraftRequest,
    ScenarioChangeDraftUpdate,
    SubmissionPackageSummary,
)
from app.domain.models import LocationSupplyRecord, Scenario
from app.ingestion.csv_loader import INPUT_TABLES, InstanceLoadError, load_instance

router = APIRouter(prefix="/api/v1", tags=["v1"])
ALLOWED_EXPORTS = frozenset({"SCHEDULE_ACCESS.csv", "SCHEDULE_OCCUPANCY.csv", "RESULTS.csv"})
NO_STORE_HEADERS = {"Cache-Control": "no-store"}
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PACKAGE_BYTES = 40 * 1024 * 1024
SUPPLY_HEADERS = ["location_id", "location_kind", "line_code", "bound", "supply_capacity"]
PUBLIC_SCHEDULE_DIR = PUBLIC_SUBMISSION_DIR


def get_service(request: Request) -> RunService:
    return request.app.state.run_service


def get_copilot(request: Request) -> CopilotService:
    return request.app.state.copilot_service


def get_draft_service(request: Request) -> DisruptionDraftService:
    return request.app.state.disruption_draft_service


def _cookie_name(run_id: str) -> str:
    return f"for_rails_run_{run_id.replace('-', '')}"


def _cookie_secure() -> bool:
    return os.getenv("FOR_RAILS_COOKIE_SECURE", "false").lower() == "true"


def _authorize(request: Request, run_id: str) -> RunRecord:
    record = get_service(request).authorize(run_id, request.cookies.get(_cookie_name(run_id)))
    if record is None:
        # Do not disclose whether a guessed run id exists to another browser.
        raise ApiException(404, "run_not_found", f"No run exists with id {run_id}.")
    return record


def _set_run_cookie(response: Response, record: RunRecord, service: RunService) -> None:
    response.set_cookie(
        key=_cookie_name(record.run_id),
        value=record.access_token,
        max_age=service._run_ttl_seconds(),
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path=f"/api/v1/runs/{record.run_id}",
    )
    # The plaintext value is needed only to issue this one browser cookie.
    record.access_token = ""


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

    with tempfile.TemporaryDirectory(prefix="for-rails-upload-") as temp_dir:
        directory = Path(temp_dir)
        file_checksums: dict[str, str] = {}
        package_bytes = 0
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
            package_bytes += len(contents)
            if len(contents) > MAX_FILE_BYTES or package_bytes > MAX_PACKAGE_BYTES:
                raise ApiException(
                    413,
                    "input_too_large",
                    "Each CSV is limited to 10 MiB and the complete input package to 40 MiB.",
                    [ApiFieldError(field="files", message=f"upload limit exceeded at {filename}")],
                )
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


async def parse_replacement_supply(record: RunRecord, upload: UploadFile) -> list[object]:
    """Read one official supply table and convert capacity deltas to all-week overrides."""
    filename = upload.filename or ""
    if filename != "04_LOCATION_SUPPLY.csv":
        raise ApiException(422, "invalid_recovery_supply_csv", "Upload the official 04_LOCATION_SUPPLY.csv filename.")
    contents = await upload.read()
    if not contents or len(contents) > MAX_FILE_BYTES:
        raise ApiException(413, "recovery_supply_too_large", "The replacement supply CSV must be between 1 byte and 10 MiB.")
    try:
        reader = csv.DictReader(io.StringIO(contents.decode("utf-8-sig"), newline=""))
    except UnicodeDecodeError as error:
        raise ApiException(422, "invalid_recovery_supply_csv", "The replacement supply CSV must be UTF-8.") from error
    if reader.fieldnames != SUPPLY_HEADERS:
        raise ApiException(
            422,
            "invalid_recovery_supply_csv",
            "04_LOCATION_SUPPLY.csv must use the exact official headers and order.",
            [ApiFieldError(field="headers", message=", ".join(SUPPLY_HEADERS))],
        )
    received: dict[str, LocationSupplyRecord] = {}
    errors: list[ApiFieldError] = []
    for row_number, row in enumerate(reader, start=2):
        try:
            item = LocationSupplyRecord.model_validate(row)
        except ValidationError as error:
            errors.append(ApiFieldError(field=f"row.{row_number}", message=error.errors()[0]["msg"]))
            continue
        if item.location_id in received:
            errors.append(ApiFieldError(field=f"row.{row_number}.location_id", message="duplicate location_id"))
        received[item.location_id] = item
    baseline = {item.location_id: item for item in record.input_instance.location_supply}
    for location_id in sorted(set(received) - set(baseline)):
        errors.append(ApiFieldError(field="location_id", message=f"unexpected location_id: {location_id}"))
    for location_id in sorted(set(baseline) - set(received)):
        errors.append(ApiFieldError(field="location_id", message=f"missing location_id: {location_id}"))
    changed: list[tuple[str, int]] = []
    for location_id, original in baseline.items():
        replacement = received.get(location_id)
        if replacement is None:
            continue
        if replacement.location_kind != original.location_kind or replacement.line_code != original.line_code or replacement.bound != original.bound:
            errors.append(ApiFieldError(field=f"location_id.{location_id}", message="location metadata must match the base input"))
        elif replacement.supply_capacity != original.supply_capacity:
            changed.append((location_id, replacement.supply_capacity))
    if errors:
        raise ApiException(422, "invalid_recovery_supply_csv", "The replacement supply CSV differs from the base input outside capacity values.", errors)
    if not changed:
        raise ApiException(422, "recovery_supply_no_changes", "The replacement supply CSV has no capacity changes to review.")
    if record.prepared_instance is None:
        raise ApiException(409, "recovery_unavailable", "Recovery requires a prepared base instance.")
    from app.api.schemas import SupplyOverride

    return [
        SupplyOverride(location_id=location_id, week=week, supply_capacity=capacity)
        for location_id, capacity in sorted(changed)
        for week in range(1, record.prepared_instance.calendar.horizon_weeks + 1)
    ]


@router.get("/health")
def health(request: Request) -> dict[str, object]:
    service = get_service(request)
    return {
        "service": "for-rails",
        "api_version": "v1",
        "status": "ok",
        "validator_status": service.validator.status().status.value,
    }


@router.get("/capabilities", response_model=CapabilityReport)
def capabilities(request: Request) -> CapabilityReport:
    service = get_service(request)
    return service.capability_report(draft_parser_available=get_draft_service(request).available)


@router.post("/demo-runs", response_model=RunView, status_code=201)
def create_public_demo_run(request: Request, response: Response) -> RunView:
    service = get_service(request)
    if not service.capability_report(draft_parser_available=get_draft_service(request).available).public_demo_recovery.available:
        raise ApiException(409, "public_demo_unavailable", "The committed public demo fixture is unavailable.")
    try:
        record = service.create_public_demo_run()
    except ValueError as error:
        raise ApiException(409, "public_demo_unavailable", str(error)) from error
    _set_run_cookie(response, record, service)
    response.headers.update(NO_STORE_HEADERS)
    return record.to_view()


@router.post("/runs", response_model=RunView, status_code=202)
async def create_run(
    request: Request,
    background_tasks: BackgroundTasks,
    response: Response,
    scenario: Scenario = Form(...),
    files: list[UploadFile] = File(...),
) -> RunView:
    service = get_service(request)
    instance = await parse_uploaded_instance(files)
    record = service.create_run(instance, scenario)
    background_tasks.add_task(service.dispatch, record.run_id)
    _set_run_cookie(response, record, service)
    response.headers.update(NO_STORE_HEADERS)
    return record.to_view()


@router.get("/runs/{run_id}", response_model=RunView)
def get_run(request: Request, run_id: str) -> RunView:
    return _authorize(request, run_id).to_view()


@router.get("/runs/{run_id}/exports/{filename}")
def download_export(request: Request, run_id: str, filename: str) -> FileResponse:
    if filename not in ALLOWED_EXPORTS:
        raise ApiException(404, "export_not_found", "The requested export filename is not supported.")
    service = get_service(request)
    view = _authorize(request, run_id).to_view()
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
    return FileResponse(path, media_type="text/csv", filename=filename, headers=NO_STORE_HEADERS)


@router.get("/public-schedule/{filename}")
def download_public_schedule(filename: str) -> FileResponse:
    """Download the published fixture outputs used to demonstrate the solver."""
    if filename not in ALLOWED_EXPORTS:
        raise ApiException(404, "export_not_found", "The requested export filename is not supported.")
    path = PUBLIC_SCHEDULE_DIR / filename
    if not path.is_file():
        raise ApiException(404, "public_export_not_found", "The published schedule output is unavailable.")
    return FileResponse(path, media_type="text/csv", filename=filename, headers=NO_STORE_HEADERS)


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
    _authorize(request, run_id)
    try:
        return get_service(request).create_submission_package(run_id).to_summary()
    except SubmissionPackageError as error:
        raise _submission_exception(error) from error


@router.get("/runs/{run_id}/submission-packages/{package_id}/download")
def download_submission_package(request: Request, run_id: str, package_id: str) -> FileResponse:
    _authorize(request, run_id)
    try:
        package = get_service(request).get_submission_package(run_id, package_id)
    except SubmissionPackageError as error:
        raise _submission_exception(error) from error
    if not package.bundle_path.is_file():
        raise ApiException(409, "submission_package_unavailable", "The submission package is no longer available.")
    return FileResponse(
        package.bundle_path,
        media_type="application/zip",
        filename=f"for-rails-submission-{package_id}.zip",
        headers=NO_STORE_HEADERS,
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
    _authorize(request, run_id)
    try:
        return get_service(request).record_organiser_evidence(run_id, package_id, payload).to_summary()
    except SubmissionPackageError as error:
        raise _submission_exception(error) from error


@router.get("/runs/{run_id}/submission-packages/{package_id}/evidence-record")
def download_evidence_record(request: Request, run_id: str, package_id: str) -> FileResponse:
    _authorize(request, run_id)
    try:
        path = get_service(request).get_evidence_record(run_id, package_id)
    except SubmissionPackageError as error:
        raise _submission_exception(error) from error
    return FileResponse(
        path,
        media_type="application/json",
        filename=f"for-rails-evidence-{package_id}.json",
        headers=NO_STORE_HEADERS,
    )


def _evidence_exception(error: EvidenceUnavailable) -> ApiException:
    message = str(error)
    if message.startswith("No scheduled activity"):
        return ApiException(404, "activity_not_found", message)
    return ApiException(409, "evidence_unavailable", message)


@router.get("/runs/{run_id}/evidence/activities/{activity_id}", response_model=EvidenceEnvelope)
def get_activity_evidence(request: Request, run_id: str, activity_id: str) -> EvidenceEnvelope:
    record = _authorize(request, run_id)
    try:
        return get_service(request).evidence_for(record, CopilotMode.ACTIVITY_EXPLANATION, activity_id)
    except EvidenceUnavailable as error:
        raise _evidence_exception(error) from error


@router.get("/runs/{run_id}/evidence/capacity-hotspots", response_model=EvidenceEnvelope)
def get_capacity_hotspots(request: Request, run_id: str) -> EvidenceEnvelope:
    record = _authorize(request, run_id)
    try:
        return get_service(request).evidence_for(record, CopilotMode.CAPACITY_HOTSPOTS)
    except EvidenceUnavailable as error:
        raise _evidence_exception(error) from error


@router.get("/runs/{run_id}/evidence/handover", response_model=EvidenceEnvelope)
def get_handover_evidence(request: Request, run_id: str) -> EvidenceEnvelope:
    record = _authorize(request, run_id)
    try:
        return get_service(request).evidence_for(record, CopilotMode.HANDOVER_SUMMARY)
    except EvidenceUnavailable as error:
        raise _evidence_exception(error) from error


@router.post("/runs/{run_id}/copilot-responses", response_model=CopilotResponse)
def create_copilot_response(request: Request, run_id: str, payload: CopilotRequest) -> CopilotResponse:
    record = _authorize(request, run_id)
    service = get_service(request)
    try:
        evidence = service.evidence_for(record, payload.mode, payload.activity_id)
    except EvidenceUnavailable as error:
        raise _evidence_exception(error) from error
    if not service.consume_copilot_request(record):
        raise ApiException(503, "copilot_unavailable", "Try the copilot again in a minute.")
    try:
        return get_copilot(request).respond(evidence, payload.mode)
    except CopilotUnavailable as error:
        raise ApiException(503, "copilot_unavailable", str(error)) from error


@router.post("/runs/{run_id}/disruption-drafts", response_model=ScenarioChangeDraft)
def create_disruption_draft(
    request: Request, run_id: str, payload: ScenarioChangeDraftRequest
) -> ScenarioChangeDraft:
    record = _authorize(request, run_id)
    service = get_service(request)
    draft_service = get_draft_service(request)
    if not service.is_public_demo(record):
        raise ApiException(
            409,
            "public_demo_only",
            "Hand-typed disruption drafts are available only for the committed public demonstration fixture.",
        )
    if not draft_service.available:
        raise ApiException(503, "disruption_parser_unavailable", "The draft parser is not enabled for this service.")
    if not service.consume_copilot_request(record):
        raise ApiException(503, "disruption_parser_unavailable", "Try the draft parser again in a minute.")
    try:
        draft = draft_service.create(record, payload.text)
        record.disruption_drafts[draft.draft_id] = draft
        return draft
    except DisruptionDraftUnavailable as error:
        raise ApiException(503, "disruption_parser_unavailable", str(error)) from error


@router.post("/runs/{run_id}/recovery-drafts/supply-csv", response_model=ScenarioChangeDraft)
async def create_supply_csv_draft(
    request: Request, run_id: str, file: UploadFile = File(...)
) -> ScenarioChangeDraft:
    """Compare a replacement official supply file with a completed base run."""
    record = _authorize(request, run_id)
    if record.status.value != "succeeded" or record.schedule is None:
        raise ApiException(409, "recovery_unavailable", "Recovery review requires a run with a candidate schedule.")
    overrides = await parse_replacement_supply(record, file)
    try:
        draft = get_draft_service(request).create_supply_csv(record, overrides)
    except DisruptionDraftUnavailable as error:
        raise ApiException(409, "recovery_unavailable", str(error)) from error
    record.disruption_drafts[draft.draft_id] = draft
    record.updated_at = datetime.now(timezone.utc)
    return draft


@router.patch("/runs/{run_id}/recovery-drafts/{draft_id}", response_model=ScenarioChangeDraft)
def update_recovery_draft(
    request: Request, run_id: str, draft_id: str, payload: ScenarioChangeDraftUpdate
) -> ScenarioChangeDraft:
    record = _authorize(request, run_id)
    draft = record.disruption_drafts.get(draft_id)
    if draft is None:
        raise ApiException(404, "recovery_draft_not_found", "No recovery draft exists for this run.")
    if record.schedule is None:
        raise ApiException(409, "recovery_unavailable", "Recovery review requires a run with a candidate schedule.")
    updated = get_draft_service(request).update(record, draft, payload)
    record.disruption_drafts[updated.draft_id] = updated
    record.updated_at = datetime.now(timezone.utc)
    return updated


@router.post("/runs/{run_id}/demo-recovery", response_model=RunView, status_code=201)
def create_public_demo_replay(
    request: Request,
    run_id: str,
    response: Response,
    payload: DemoRecoveryRequest | None = None,
) -> RunView:
    service = get_service(request)
    base = _authorize(request, run_id)
    if not service.is_public_demo(base):
        raise ApiException(
            409,
            "public_demo_only",
            "Recovery replay is available only for the committed public demonstration fixture.",
        )
    record = service.create_public_demo_replay(run_id, draft_id=payload.draft_id if payload else None)
    if record is None:
        if payload and payload.draft_id:
            raise ApiException(
                422,
                "disruption_draft_not_ready",
                "A known, fully resolved public draft is required before this replay can be confirmed.",
            )
        raise ApiException(409, "public_demo_unavailable", "The public recovery replay could not be created.")
    _set_run_cookie(response, record, service)
    response.headers.update(NO_STORE_HEADERS)
    return record.to_view()


@router.post("/runs/{run_id}/recovery", response_model=RunView, status_code=202)
def create_recovery(
    request: Request,
    run_id: str,
    change: ScenarioChange,
    background_tasks: BackgroundTasks,
    response: Response,
) -> RunView:
    if change.confirmed_at is None:
        raise ApiException(
            422,
            "scenario_change_unconfirmed",
            "A recovery request must include an explicit confirmation timestamp.",
            [ApiFieldError(field="confirmed_at", message="confirmation is required")],
        )
    service = get_service(request)
    base_record = _authorize(request, run_id)
    recovery_capability = service.capability_report(
        draft_parser_available=get_draft_service(request).available
    ).recovery
    if not recovery_capability.available:
        raise ApiException(
            409,
            "recovery_solver_unavailable",
            "Recovery optimisation is not connected yet; no revised live schedule can be created.",
        )
    base = base_record.to_view()
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
    if base.scenario not in recovery_capability.supported_scenarios:
        raise ApiException(
            409,
            "recovery_scenario_unavailable",
            f"Recovery optimisation is currently available only for Scenario C, not Scenario {base.scenario.value}.",
        )
    record = service.create_recovery(run_id, change)
    if record is None:
        raise ApiException(409, "recovery_unavailable", "Recovery is unavailable for this run.")
    background_tasks.add_task(service.dispatch, record.run_id)
    _set_run_cookie(response, record, service)
    response.headers.update(NO_STORE_HEADERS)
    return record.to_view()


@router.post("/runs/{run_id}/recovery-drafts/{draft_id}/confirm", response_model=RunView, status_code=202)
def confirm_recovery_draft(
    request: Request,
    run_id: str,
    draft_id: str,
    background_tasks: BackgroundTasks,
    response: Response,
) -> RunView:
    record = _authorize(request, run_id)
    draft = record.disruption_drafts.get(draft_id)
    if draft is None:
        raise ApiException(404, "recovery_draft_not_found", "No recovery draft exists for this run.")
    if draft.status.value != "ready":
        raise ApiException(422, "recovery_draft_not_ready", "Resolve the recovery draft before confirmation.")
    change = draft.change.model_copy(
        update={"confirmed_at": datetime.now(timezone.utc), "requested_by": "controller"}
    )
    return create_recovery(request, run_id, change, background_tasks, response)
