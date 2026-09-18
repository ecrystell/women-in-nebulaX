"""Write only the official three-file answer-key format."""

from __future__ import annotations

import csv
from pathlib import Path

from app.domain.models import ScenarioSchedule

ACCESS_HEADERS = ["activity_id", "access_seq", "week", "eclo", "access_night"]
OCCUPANCY_HEADERS = ["activity_id", "week", "location_id", "co_share_group"]
RESULT_HEADERS = ["scenario", "contract_number", "simulated_completion_date", "overrun_days"]


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_submission(schedule: ScenarioSchedule, output_dir: Path) -> dict[str, Path]:
    """Export an answer key without assessing whether it is feasible."""

    output_dir.mkdir(parents=True, exist_ok=True)
    access_path = output_dir / "SCHEDULE_ACCESS.csv"
    occupancy_path = output_dir / "SCHEDULE_OCCUPANCY.csv"
    results_path = output_dir / "RESULTS.csv"

    _write_csv(
        access_path,
        ACCESS_HEADERS,
        [assignment.model_dump() for assignment in schedule.access_assignments],
    )
    _write_csv(
        occupancy_path,
        OCCUPANCY_HEADERS,
        [assignment.model_dump() for assignment in schedule.occupancy_assignments],
    )
    _write_csv(
        results_path,
        RESULT_HEADERS,
        [
            {
                **result.model_dump(exclude={"scenario"}),
                "scenario": result.scenario.value,
                "simulated_completion_date": result.simulated_completion_date.isoformat(),
            }
            for result in schedule.contract_results
        ],
    )
    return {
        "SCHEDULE_ACCESS.csv": access_path,
        "SCHEDULE_OCCUPANCY.csv": occupancy_path,
        "RESULTS.csv": results_path,
    }
