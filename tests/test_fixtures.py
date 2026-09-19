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
        # The manifest records the upstream LF bytes. Git may materialise the
        # CSV fixtures with CRLF on Windows, which must not look like a content
        # change to this source-integrity check.
        normalized = fixture.read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(normalized).hexdigest() == expected_hash
