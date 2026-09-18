from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DATA = ROOT / "data" / "public-instance"


def test_public_fixture_checksums_match_manifest() -> None:
    manifest = json.loads((PUBLIC_DATA / "manifest.json").read_text(encoding="utf-8"))

    for relative_path, expected_hash in manifest["files"].items():
        fixture = PUBLIC_DATA / relative_path
        assert fixture.is_file(), f"missing public fixture: {relative_path}"
        assert hashlib.sha256(fixture.read_bytes()).hexdigest() == expected_hash
