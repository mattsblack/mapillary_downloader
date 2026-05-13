"""Tests for collection finalization helpers."""

import gzip
import json

from mapillary_downloader import paths
from mapillary_downloader.finalizer import compress_metadata


def test_compress_metadata_preserves_legacy_filename(tmp_path):
    metadata_file = tmp_path / paths.METADATA_JSONL
    metadata_file.write_text(json.dumps({"id": "img1"}) + "\n")

    compress_metadata(tmp_path)

    compressed = tmp_path / paths.METADATA_JSONL_GZ
    assert not metadata_file.exists()
    assert compressed.exists()
    with gzip.open(compressed, "rt") as f:
        assert json.loads(f.readline()) == {"id": "img1"}
