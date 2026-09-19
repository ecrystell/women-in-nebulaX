"""Small Vertex AI adapter for rendering already-built evidence.

The adapter accepts an :class:`EvidenceEnvelope`, not an instance, CSV, or
schedule.  Keeping that type boundary makes accidental hidden-data expansion
testable and prevents Gemini from becoming a second scheduler.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas import CopilotMode, CopilotResponse, EvidenceEnvelope


DISCLAIMER = "Organiser verification is unavailable or unverified; this explanation does not establish feasibility."


class CopilotUnavailable(RuntimeError):
    """Vertex is disabled, unavailable, rate-limited, or returned unsafe output."""


class _Narrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=2000)
    # The API attaches the exact server-built EvidenceEnvelope to every
    # response, so a provider does not need to echo an opaque UUID merely to
    # establish grounding.  It remains accepted and checked when present for
    # backwards compatibility with earlier deployed prompts.
    schedule_id: str | None = None


class NarrativeGenerator(Protocol):
    model_name: str

    def generate(self, evidence: EvidenceEnvelope, mode: CopilotMode) -> str: ...


class VertexGeminiGenerator:
    """Uses Cloud Run Application Default Credentials; never accepts an API key."""

    def __init__(self) -> None:
        self.enabled = os.getenv("FOR_RAILS_AI_ENABLED", "false").lower() == "true"
        self.project = os.getenv("FOR_RAILS_GCP_PROJECT", "").strip()
        self.location = os.getenv("FOR_RAILS_VERTEX_LOCATION", "global").strip() or "global"
        self.model_name = os.getenv("FOR_RAILS_GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"

    def generate(self, evidence: EvidenceEnvelope, mode: CopilotMode) -> str:
        if not self.enabled or not self.project:
            raise CopilotUnavailable("The grounded copilot is not enabled for this service.")
        try:
            from google import genai
            from google.genai import types
        except ImportError as error:  # pragma: no cover - exercised by production image smoke test
            raise CopilotUnavailable("The Vertex AI client is not installed.") from error

        instruction = (
            "You are the For Rails Copilot. Explain only the supplied deterministic evidence in plain, "
            "controller-friendly language. The reader does not know compact CSV identifiers. Prefer "
            "placement_summaries, closure_footprint_labels, and location_label fields over raw IDs. "
            "For example, say 'Platform on Line Beta, at interchange H01, westbound' rather than "
            "'PLAT:BET:H01:WB'. If traceability requires an identifier, put the plain-language meaning "
            "first and the identifier in parentheses. Use short prose or bullets and expand ECLO once "
            "as 'early closure / late opening'. Explain only the supplied deterministic evidence. "
            "Do not add facts, recommend placements, schedule work, modify a plan, call tools, "
            "claim a plan is feasible, safe, approved, or organiser-verified. "
            "State uncertainty plainly. Return JSON only with the key answer. "
            "The server, not you, attaches the evidence reference."
        )
        contents = json.dumps(
            {"mode": mode.value, "evidence": evidence.model_dump(mode="json")},
            separators=(",", ":"),
        )
        try:
            client = genai.Client(
                # This selects the Vertex AI backend and therefore uses the
                # Cloud Run service account's Application Default Credentials.
                # ``enterprise=True`` selects a different Gemini Enterprise
                # surface and can yield a response shape that is incompatible
                # with this bounded Vertex-only integration.
                vertexai=True,
                project=self.project,
                location=self.location,
                http_options=types.HttpOptions(api_version="v1"),
            )
            response = client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=instruction,
                    temperature=0.2,
                    max_output_tokens=600,
                    response_mime_type="application/json",
                    # Ask Vertex to enforce the bounded response shape before
                    # it reaches our second, independent Pydantic check.  A
                    # MIME type alone requests JSON but does not guarantee the
                    # two fields required by this evidence-only endpoint.
                    response_schema=_Narrative,
                ),
            )
            # ``parsed`` is the SDK's schema-aware representation. Prefer it
            # over ``text``: depending on the provider revision, text can be
            # fenced or omitted even though Vertex successfully parsed the
            # response against ``response_schema``. The service below still
            # independently validates this JSON before returning it.
            parsed = getattr(response, "parsed", None)
            if isinstance(parsed, BaseModel):
                return parsed.model_dump_json()
            if isinstance(parsed, dict):
                return json.dumps(parsed, separators=(",", ":"))
            if isinstance(parsed, str):
                return parsed
            return response.text or ""
        except Exception as error:  # Deliberately do not expose provider payloads or prompt data.
            raise CopilotUnavailable("Vertex AI could not produce a grounded response.") from error


class CopilotService:
    def __init__(self, generator: NarrativeGenerator | None = None) -> None:
        self.generator = generator or VertexGeminiGenerator()

    def respond(self, evidence: EvidenceEnvelope, mode: CopilotMode) -> CopilotResponse:
        try:
            decoded = _Narrative.model_validate_json(_normalise_json(self.generator.generate(evidence, mode)))
        except CopilotUnavailable:
            raise
        except Exception as error:
            raise CopilotUnavailable("Vertex AI returned an invalid grounded response.") from error
        if (
            (decoded.schedule_id is not None and decoded.schedule_id != evidence.schedule_id)
            or _contains_prohibited_claim(decoded.answer)
        ):
            raise CopilotUnavailable("Vertex AI returned a response outside the grounded copilot policy.")
        return CopilotResponse(
            mode=mode,
            answer=decoded.answer,
            evidence=evidence,
            model=self.generator.model_name,
            generated_at=datetime.now(timezone.utc),
            verification_disclaimer=DISCLAIMER,
        )


def _normalise_json(raw: str) -> str:
    """Accept a JSON response even when a provider unnecessarily wraps it in a fence.

    The structured schema is still parsed and validated immediately afterwards.
    This does not accept prose before or after the JSON value.
    """

    value = raw.strip()
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    if len(lines) < 3 or not lines[-1].strip().startswith("```"):
        return value
    return "\n".join(lines[1:-1]).strip()


def _contains_prohibited_claim(answer: str) -> bool:
    text = answer.lower()
    prohibited = (
        "is feasible",
        "are feasible",
        "feasibility is confirmed",
        "organiser approved",
        "organizer approved",
        "safe to operate",
        "i scheduled",
        "i changed the schedule",
    )
    return any(value in text for value in prohibited)
