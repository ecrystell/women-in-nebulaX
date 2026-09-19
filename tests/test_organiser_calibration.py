"""Keep supplied organiser closure traces as external calibration evidence."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.validation.preflight import validate_submission


ROOT = Path(__file__).resolve().parents[1]
INSTANCE = ROOT / "data" / "public-instance"
PAIR_PATTERN = re.compile(r"wk(\d+): (A\d+) inside closure of \[(.*?)\]")


def closure_pairs(text: str) -> set[tuple[int, str, str]]:
    return {
        (int(week), victim, source)
        for week, victim, sources in PAIR_PATTERN.findall(text)
        for source in re.findall(r"A\d+", sources)
    }


@pytest.mark.parametrize("scenario", ["scenario_a", "scenario_c"])
def test_supplied_organiser_trace_is_preserved_without_inventing_local_timing(scenario: str) -> None:
    submission = ROOT / "tested_data" / scenario
    organiser = closure_pairs((submission / "result.txt").read_text(encoding="utf-8"))
    report = validate_submission(INSTANCE, submission)
    assert organiser
    assert any("organiser-validator-only" in warning for warning in report.detail["warnings"])
    assert "closure" not in {item["rule"] for item in report.hard_violations}
