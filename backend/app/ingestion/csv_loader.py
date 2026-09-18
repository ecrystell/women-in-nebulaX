"""Strict CSV shape loader for the eight PS1 input tables."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.domain.models import (
    ActivityRecord,
    BufferLocationRecord,
    InstanceBundle,
    LineRecord,
    LocationSupplyRecord,
    ParameterRecord,
    ProjectRecord,
    SectorRecord,
    StationRecord,
)


T = TypeVar("T", bound=BaseModel)

INPUT_TABLES: dict[str, tuple[str, type[BaseModel], str]] = {
    "01_LINES.csv": ("lines", LineRecord, "01_LINES"),
    "02_STATIONS.csv": ("stations", StationRecord, "02_STATIONS"),
    "03_SECTORS.csv": ("sectors", SectorRecord, "03_SECTORS"),
    "04_LOCATION_SUPPLY.csv": ("location_supply", LocationSupplyRecord, "04_LOCATION_SUPPLY"),
    "05_BUFFER_LOCATION.csv": ("buffer_locations", BufferLocationRecord, "05_BUFFER_LOCATION"),
    "06_PARAMETERS.csv": ("parameters", ParameterRecord, "06_PARAMETERS"),
    "07_PROJECT_DETAILS.csv": ("projects", ProjectRecord, "07_PROJECT_DETAILS"),
    "08_ACTIVITY_DETAILS.csv": ("activities", ActivityRecord, "08_ACTIVITY_DETAILS"),
}


class InstanceLoadError(ValueError):
    """Describes a malformed official CSV with enough context to fix it."""


def expected_headers(model: type[BaseModel]) -> list[str]:
    return list(model.model_fields)


def _load_table(path: Path, model: type[T]) -> list[T]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        actual_headers = reader.fieldnames
        wanted_headers = expected_headers(model)
        if actual_headers is None:
            raise InstanceLoadError(f"{path.name}: CSV is missing a header row")
        if actual_headers != wanted_headers:
            raise InstanceLoadError(
                f"{path.name}: expected headers {wanted_headers}, received {actual_headers}"
            )

        records: list[T] = []
        for row_number, row in enumerate(reader, start=2):
            try:
                records.append(model.model_validate(row))
            except ValidationError as error:
                raise InstanceLoadError(f"{path.name}: row {row_number}: {error}") from error
    return records


def load_instance(data_dir: Path) -> InstanceBundle:
    """Load exactly the official eight-file package; no topology checks occur here."""

    missing = [filename for filename in INPUT_TABLES if not (data_dir / filename).is_file()]
    unexpected = [
        path.name
        for path in data_dir.glob("*.csv")
        if path.name not in INPUT_TABLES
    ]
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing {missing}")
        if unexpected:
            details.append(f"unexpected {unexpected}")
        raise InstanceLoadError("input package must contain exactly eight CSVs: " + "; ".join(details))

    tables: dict[str, Any] = {}
    for filename, (field_name, model, _) in INPUT_TABLES.items():
        tables[field_name] = _load_table(data_dir / filename, model)
    return InstanceBundle.model_validate(tables)
