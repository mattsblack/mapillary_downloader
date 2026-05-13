"""Tests for stable collection naming and paths."""

from mapillary_downloader import paths
from mapillary_downloader.collection import CollectionId, CollectionPaths


def test_collection_id_preserves_legacy_names():
    assert CollectionId("gaz", "original").name == "mapillary-gaz-original"
    assert CollectionId("gaz", "1024", is_webp=True).name == "mapillary-gaz-1024-webp"


def test_collection_id_parses_legacy_names_and_paths():
    collection_id = CollectionId.parse("/tmp/mapillary-user-with-dash-original-webp")

    assert collection_id == CollectionId("user-with-dash", "original", is_webp=True)
    assert CollectionId.parse("not-mapillary-user-original") is None


def test_collection_paths_preserve_staging_and_final_layout(tmp_path):
    collection_id = CollectionId("testuser", "original")
    collection_paths = CollectionPaths.for_collection(tmp_path / "output", collection_id, tmp_path / "cache")

    assert collection_paths.staging_dir == tmp_path / "cache" / "mapillary-testuser-original"
    assert collection_paths.final_dir == tmp_path / "output" / "mapillary-testuser-original"
    assert collection_paths.metadata_file.name == paths.METADATA_JSONL
    assert collection_paths.compressed_metadata_file.name == paths.METADATA_JSONL_GZ
    assert collection_paths.progress_file.name == paths.PROGRESS_JSON
    assert collection_paths.cursor_file.name == paths.API_CURSOR
