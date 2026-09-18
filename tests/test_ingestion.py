from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.ingestion.csv_loader import InstanceLoadError, load_instance


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DATA = ROOT / "data" / "public-instance"


def test_loads_official_public_instance() -> None:
    bundle = load_instance(PUBLIC_DATA)

    assert len(bundle.lines) == 2
    assert len(bundle.stations) == 20
    assert len(bundle.projects) == 14
    assert len(bundle.activities) == 54


def test_rejects_unknown_header(tmp_path: Path) -> None:
    shutil.copytree(PUBLIC_DATA, tmp_path / "instance")
    target = tmp_path / "instance" / "01_LINES.csv"
    target.write_text("line_code,line_name,extra\nALP,Line Alpha,unexpected\n", encoding="utf-8")

    with pytest.raises(InstanceLoadError, match="expected headers"):
        load_instance(tmp_path / "instance")


@pytest.mark.parametrize(
    ("filename", "old_value", "new_value"),
    [
        ("05_BUFFER_LOCATION.csv", "Live,2,1", "Invented work type,2,1"),
        ("07_PROJECT_DETAILS.csv", ",3,2027-08-01", ",4,2027-08-01"),
        (
            "08_ACTIVITY_DETAILS.csv",
            "A001,C001,Renewal,SEC:BET:S15_S16:EB,SEC:BET:S16_S17:EB,2,2027-05-24",
            "A001,C001,Renewal,SEC:BET:S15_S16:EB,SEC:BET:S16_S17:EB,0,not-a-date",
        ),
    ],
)
def test_rejects_invalid_enum_and_numeric_domains(
    tmp_path: Path, filename: str, old_value: str, new_value: str
) -> None:
    instance_dir = tmp_path / "instance"
    shutil.copytree(PUBLIC_DATA, instance_dir)
    target = instance_dir / filename
    text = target.read_text(encoding="utf-8")
    text = text.replace(old_value, new_value, 1)
    target.write_text(text, encoding="utf-8")

    with pytest.raises(InstanceLoadError, match=filename):
        load_instance(instance_dir)
