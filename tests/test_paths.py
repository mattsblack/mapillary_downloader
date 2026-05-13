"""Tests for stable state-file constants."""

from mapillary_downloader import paths


def test_stable_state_file_names():
    assert paths.METADATA_JSONL == "metadata.jsonl"
    assert paths.METADATA_JSONL_GZ == "metadata.jsonl.gz"
    assert paths.PROGRESS_JSON == "progress.json"
    assert paths.API_CURSOR == ".api_cursor"
    assert paths.CHUNKS_JSON == "chunks.json"
    assert paths.PAYLOAD_DIR == "payload"
    assert paths.STATS_CACHE_JSON == ".stats.json"
    assert paths.GEONAMES_TSV_GZ == "planet-latest_geonames.tsv.gz"
    assert paths.LOCATIONS_TSV == "locations.tsv"
    assert paths.LOCATIONS_JSON == "locations.json"
    assert paths.LEADERBOARDS_JSON == "leaderboards.json"
