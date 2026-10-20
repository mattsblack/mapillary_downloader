"""Resume checkpoints survive replay, file replacement, and failed transactions."""

import json

import pytest

from mapillary_downloader.progress import ProgressStore


def test_migrates_legacy_once_and_preserves_incremental_checkpoints(tmp_path):
    legacy = tmp_path / "progress.json"
    legacy.write_text(json.dumps({"original": ["old"], "1024": ["other-quality"]}))
    metadata = tmp_path / "metadata.jsonl"
    metadata.write_bytes(b'{"id":"old"}\n{"id":"retry"}\n')
    database = tmp_path / "progress.sqlite3"
    store = ProgressStore(database, "original")
    assert store.load(legacy) == ({"old"}, {})
    retry = {"retry": {"id": "retry", "thumb_original_url": "url"}}
    store.save({"new"}, retry, metadata, metadata.stat().st_size)
    legacy.write_text("{}")

    resumed = ProgressStore(database, "original")
    assert resumed.load(legacy) == ({"old", "new"}, retry)
    assert resumed.resume_offset(metadata) == metadata.stat().st_size
    with resumed.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM completed WHERE image_id = 'other-quality'").fetchone()[0] == 0


def test_offset_invalidated_when_metadata_replaced_or_truncated(tmp_path):
    metadata = tmp_path / "metadata.jsonl"
    metadata.write_bytes(b"first\nsecond\n")
    store = ProgressStore(tmp_path / "progress.sqlite3", "original")
    store.load(tmp_path / "missing.json")
    store.save([], {}, metadata, metadata.stat().st_size)
    replacement = tmp_path / "replacement"
    replacement.write_bytes(metadata.read_bytes())
    replacement.replace(metadata)
    assert store.resume_offset(metadata) == 0
    store.save([], {}, metadata, metadata.stat().st_size)
    metadata.write_bytes(b"first\n")
    assert store.resume_offset(metadata) == 0


def test_failed_checkpoint_rolls_back_ids_retries_and_offset(tmp_path):
    metadata = tmp_path / "metadata.jsonl"
    metadata.write_bytes(b"first\nsecond\n")
    store = ProgressStore(tmp_path / "progress.sqlite3", "original")
    legacy = tmp_path / "missing.json"
    store.load(legacy)
    retries = {"retry": {"id": "retry"}}
    store.save({"old"}, retries, metadata, 6)
    with pytest.raises(TypeError):
        store.save({"uncommitted"}, {"broken": {"value": object()}}, metadata, 13)
    assert store.load(legacy) == ({"old"}, retries)
    assert store.resume_offset(metadata) == 6
