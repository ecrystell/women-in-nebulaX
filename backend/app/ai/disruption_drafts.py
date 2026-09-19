"""Public-fixture-only, review-only disruption draft parsing.

This module deliberately has no import from solver, exporter, organiser
submission, or recovery dispatch code.  It can interpret a bounded controller
request but cannot execute it.
"""

from __future__ import annotations

import json
import os
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas import (
    ApiFieldError,
    ScenarioChange,
    ScenarioChangeDraft,
    ScenarioChangeDraftStatus,
    ScenarioChangeDraftUpdate,
    PlacementKey,
    RecoveryDraftSource,
    SupplyOverride,
)
from app.api.run_service import RunRecord


class DisruptionDraftUnavailable(RuntimeError):
    """Vertex is disabled, failed, or supplied an invalid structured draft."""


class _DraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supply_overrides: list[SupplyOverride] = Field(default_factory=list, max_length=12)
    # Vertex structured output supports a concrete object schema.  An
    # untyped ``dict[str, object]`` becomes an open-ended JSON object and can
    # be rejected before Gemini is invoked, so keep this aligned with the
    # API's existing, bounded placement-key contract.
    locked_placements: list[PlacementKey] = Field(default_factory=list, max_length=24)
    rationale: str | None = Field(default=None, max_length=500)
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    unresolved_references: list[str] = Field(default_factory=list, max_length=12)


class DraftGenerator(Protocol):
    @property
    def available(self) -> bool: ...

    def generate(self, context: dict[str, object]) -> str: ...


class VertexDraftGenerator:
    """Vertex-only draft generator using Cloud Run service-account credentials."""

    @property
    def available(self) -> bool:
        return (
            os.getenv("FOR_RAILS_AI_ENABLED", "false").lower() == "true"
            and bool(os.getenv("FOR_RAILS_GCP_PROJECT", "").strip())
        )

    def generate(self, context: dict[str, object]) -> str:
        if not self.available:
            raise DisruptionDraftUnavailable("The draft parser is not enabled for this service.")
        try:
            from google import genai
            from google.genai import types
        except ImportError as error:  # pragma: no cover - production dependency boundary
            raise DisruptionDraftUnavailable("The Vertex AI client is not installed.") from error
        instruction = (
            "You convert a controller's disruption request into a review-only JSON draft. "
            "Use only the supplied public reference list. Never invent IDs, make a schedule, "
            "claim feasibility, call tools, or set confirmation. If a reference is ambiguous or "
            "missing, leave it out and explain it in unresolved_references. Return exactly one JSON "
            "object with only these keys: supply_overrides (an array of objects with location_id, week, "
            "and supply_capacity), locked_placements (an array of objects with activity_id and access_seq), "
            "rationale (string or null), assumptions (array of strings), and unresolved_references "
            "(array of strings). Return JSON only."
        )
        try:
            client = genai.Client(
                vertexai=True,
                project=os.environ["FOR_RAILS_GCP_PROJECT"].strip(),
                location=os.getenv("FOR_RAILS_VERTEX_LOCATION", "global").strip() or "global",
                http_options=types.HttpOptions(api_version="v1"),
            )
            response = client.models.generate_content(
                model=os.getenv("FOR_RAILS_GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash",
                contents=json.dumps(context, separators=(",", ":")),
                config=types.GenerateContentConfig(
                    system_instruction=instruction,
                    temperature=0,
                    max_output_tokens=700,
                    response_mime_type="application/json",
                    # The Vertex endpoint accepts the model and JSON MIME type, but its
                    # structured-output schema subset can reject a nested draft model
                    # before generation.  Pydantic below remains the authoritative,
                    # strict schema validator for the returned JSON.
                ),
            )
            parsed = getattr(response, "parsed", None)
            if isinstance(parsed, BaseModel):
                return parsed.model_dump_json()
            if isinstance(parsed, dict):
                return json.dumps(parsed, separators=(",", ":"))
            if isinstance(parsed, str):
                return parsed
            return response.text or ""
        except Exception as error:
            raise DisruptionDraftUnavailable("Vertex AI could not produce a disruption draft.") from error


class DisruptionDraftService:
    def __init__(self, generator: DraftGenerator | None = None) -> None:
        self.generator = generator or VertexDraftGenerator()

    @property
    def available(self) -> bool:
        return self.generator.available

    def create(self, record: RunRecord, text: str) -> ScenarioChangeDraft:
        if not self.available:
            raise DisruptionDraftUnavailable("The draft parser is not enabled for this service.")
        if record.schedule is None or record.prepared_instance is None:
            raise DisruptionDraftUnavailable("A public demo schedule is required before parsing a disruption.")
        context = {
            "request": text,
            "scenario": record.scenario.value,
            "schedule_id": record.schedule.schedule_id,
            "horizon_weeks": record.prepared_instance.calendar.horizon_weeks,
            # These are identifiers only, not source rows, placements, exports,
            # checksums, organiser metadata, or raw CSV data.
            "valid_supply_locations": sorted(record.prepared_instance.supply)[:200],
            "valid_placement_keys": [
                {"activity_id": item.activity_id, "access_seq": item.access_seq}
                for item in record.schedule.placements[:200]
            ],
        }
        try:
            parsed = _DraftOutput.model_validate_json(self.generator.generate(context))
        except DisruptionDraftUnavailable:
            raise
        except Exception as error:
            raise DisruptionDraftUnavailable("Vertex AI returned an invalid disruption draft.") from error
        prose = " ".join(
            part
            for part in [parsed.rationale or "", *parsed.assumptions, *parsed.unresolved_references]
        ).lower()
        if any(phrase in prose for phrase in ("feasible", "infeasible", "validated", "optimised", "optimized")):
            raise DisruptionDraftUnavailable("Vertex AI returned an unsafe disruption draft.")

        errors = self._validate(record, parsed.supply_overrides, parsed.locked_placements)
        unresolved = list(dict.fromkeys(parsed.unresolved_references))
        if not parsed.supply_overrides and not parsed.locked_placements and not unresolved:
            unresolved.append("No supply override or scheduled placement lock was resolved from the request.")
        change = ScenarioChange(
            change_id=str(uuid4()),
            base_schedule_id=record.schedule.schedule_id,
            scenario=record.scenario,
            supply_overrides=parsed.supply_overrides,
            locked_placements=parsed.locked_placements,
            requested_by="controller-draft",
            confirmed_at=None,
            rationale=parsed.rationale,
        )
        return ScenarioChangeDraft(
            draft_id=str(uuid4()),
            change=change,
            source=RecoveryDraftSource.NATURAL_LANGUAGE,
            assumptions=list(dict.fromkeys(parsed.assumptions)),
            unresolved_references=unresolved,
            field_errors=errors,
            status=(
                ScenarioChangeDraftStatus.READY
                if not errors and not unresolved
                else ScenarioChangeDraftStatus.NEEDS_REVIEW
            ),
        )

    def create_supply_csv(self, record: RunRecord, overrides: list[SupplyOverride]) -> ScenarioChangeDraft:
        """Create an all-week draft from a verified replacement supply table."""
        if record.schedule is None or record.prepared_instance is None:
            raise DisruptionDraftUnavailable("A completed base schedule is required before reviewing supply changes.")
        return self._draft(
            record,
            supply_overrides=overrides,
            locked_placements=[],
            rationale="Capacity changes imported from a replacement 04_LOCATION_SUPPLY.csv.",
            source=RecoveryDraftSource.SUPPLY_CSV,
        )

    def update(self, record: RunRecord, draft: ScenarioChangeDraft, update: ScenarioChangeDraftUpdate) -> ScenarioChangeDraft:
        """Apply controller review edits and recompute deterministic draft validity."""
        return self._draft(
            record,
            supply_overrides=update.supply_overrides,
            locked_placements=update.locked_placements,
            rationale=update.rationale,
            source=RecoveryDraftSource.MANUAL_REVIEW,
            assumptions=draft.assumptions,
        )

    def _draft(
        self,
        record: RunRecord,
        *,
        supply_overrides: list[SupplyOverride],
        locked_placements: list[object],
        rationale: str | None,
        source: RecoveryDraftSource,
        assumptions: list[str] | None = None,
    ) -> ScenarioChangeDraft:
        assert record.schedule is not None
        errors = self._validate(record, supply_overrides, locked_placements)
        typed_locks = []
        for item in locked_placements:
            try:
                typed_locks.append(item if hasattr(item, "activity_id") else {"activity_id": item["activity_id"], "access_seq": item["access_seq"]})
            except (KeyError, TypeError):
                continue
        change = ScenarioChange(
            change_id=str(uuid4()),
            base_schedule_id=record.schedule.schedule_id,
            scenario=record.scenario,
            supply_overrides=supply_overrides,
            locked_placements=typed_locks,
            requested_by="controller-review",
            confirmed_at=None,
            rationale=rationale,
        )
        unresolved = [] if supply_overrides or typed_locks else ["Select a supply change or lock at least one scheduled placement."]
        return ScenarioChangeDraft(
            draft_id=str(uuid4()),
            change=change,
            source=source,
            assumptions=assumptions or [],
            unresolved_references=unresolved,
            field_errors=errors,
            status=ScenarioChangeDraftStatus.READY if not errors and not unresolved else ScenarioChangeDraftStatus.NEEDS_REVIEW,
        )

    @staticmethod
    def _validate(
        record: RunRecord, supply_overrides: list[SupplyOverride], locked_placements: list[object]
    ) -> list[ApiFieldError]:
        assert record.schedule is not None and record.prepared_instance is not None
        errors: list[ApiFieldError] = []
        seen_overrides: set[tuple[str, int]] = set()
        horizon = record.prepared_instance.calendar.horizon_weeks
        for index, override in enumerate(supply_overrides):
            key = (override.location_id, override.week)
            field = f"supply_overrides.{index}"
            if override.location_id not in record.prepared_instance.supply:
                errors.append(ApiFieldError(field=field, message="unknown supply location"))
            if override.week > horizon:
                errors.append(ApiFieldError(field=field, message=f"week exceeds the {horizon}-week planning horizon"))
            if key in seen_overrides:
                errors.append(ApiFieldError(field=field, message="duplicate location/week supply override"))
            seen_overrides.add(key)

        valid_locks = {(item.activity_id, item.access_seq) for item in record.schedule.placements}
        seen_locks: set[tuple[str, int]] = set()
        for index, raw_lock in enumerate(locked_placements):
            try:
                if hasattr(raw_lock, "activity_id"):
                    activity_id = str(raw_lock.activity_id)
                    access_seq = int(raw_lock.access_seq)
                else:
                    activity_id = str(raw_lock["activity_id"])
                    access_seq = int(raw_lock["access_seq"])
            except (KeyError, TypeError, ValueError, AttributeError):
                errors.append(ApiFieldError(field=f"locked_placements.{index}", message="invalid placement key"))
                continue
            key = (activity_id, access_seq)
            if key not in valid_locks:
                errors.append(ApiFieldError(field=f"locked_placements.{index}", message="unknown scheduled placement key"))
            if key in seen_locks:
                errors.append(ApiFieldError(field=f"locked_placements.{index}", message="duplicate placement lock"))
            seen_locks.add(key)
        return errors
