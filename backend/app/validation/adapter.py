"""Never substitute local checks for the organiser's feasibility decision."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class ValidationStatus(str, Enum):
    UNAVAILABLE = "unavailable"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ValidationStatus
    feasible: bool | None = None
    message: str
    hard_violations: list[dict[str, object]] = []
    soft_scores: dict[str, object] = {}


class OfficialValidatorAdapter:
    """Integration seam for the validator package supplied by organisers.

    Phase 0 intentionally has no fallback that can mark a schedule feasible.
    """

    def status(self) -> ValidationReport:
        return ValidationReport(
            status=ValidationStatus.UNAVAILABLE,
            feasible=None,
            message=(
                "The organiser validator is not installed. Local CSV contract checks do not "
                "establish schedule feasibility."
            ),
        )

    def local_contract_check(self) -> ValidationReport:
        return ValidationReport(
            status=ValidationStatus.UNVERIFIED,
            feasible=None,
            message=(
                "CSV schema and export contracts may be checked locally, but the schedule "
                "remains unverified until the organiser validator runs."
            ),
        )
