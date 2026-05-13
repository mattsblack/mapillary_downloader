"""Tests for Internet Archive metadata helpers."""

import gzip
import json

from mapillary_downloader.ia_meta import get_date_range


def test_get_date_range_uses_utc(tmp_path):
    """Timestamp-to-date conversion should not depend on the host timezone."""
    metadata_file = tmp_path / "metadata.jsonl.gz"
    with gzip.open(metadata_file, "wt") as f:
        f.write(json.dumps({"id": "before_midnight", "captured_at": 1704067199000}) + "\n")
        f.write(json.dumps({"id": "after_midnight", "captured_at": 1704067200000}) + "\n")

    assert get_date_range(metadata_file) == ("2023-12-31", "2024-01-01")
