"""Tests for metadata reader."""

import gzip
import json

from mapillary_downloader.metadata_reader import MetadataReader


def test_metadata_reader_empty(tmp_path):
    """Test reading from non-existent file."""
    reader = MetadataReader(tmp_path / "nonexistent.jsonl")

    assert not reader.is_complete


def test_metadata_reader_completion_marker(tmp_path):
    """Test completion marker detection."""
    metadata_file = tmp_path / "metadata.jsonl"

    # Write some test data with completion marker
    with open(metadata_file, "w") as f:
        f.write(json.dumps({"id": "img1", "thumb_original_url": "http://example.com/1.jpg"}) + "\n")
        f.write(json.dumps({"__complete__": True}) + "\n")
        f.write(json.dumps({"id": "img2", "thumb_original_url": "http://example.com/2.jpg"}) + "\n")

    reader = MetadataReader(metadata_file)

    assert reader.is_complete


def test_metadata_reader_mark_complete(tmp_path):
    """Test marking metadata as complete."""
    metadata_file = tmp_path / "metadata.jsonl"

    # Write some test data
    with open(metadata_file, "w") as f:
        f.write(json.dumps({"id": "img1"}) + "\n")

    # Mark as complete
    MetadataReader.mark_complete(metadata_file)

    # Verify marker was added
    reader = MetadataReader(metadata_file)
    assert reader.is_complete


def test_metadata_reader_gzip(tmp_path):
    """Test reading gzipped metadata file."""
    metadata_file = tmp_path / "metadata.jsonl.gz"

    # Write gzipped test data
    with gzip.open(metadata_file, "wt") as f:
        f.write(json.dumps({"id": "img1", "thumb_original_url": "http://example.com/1.jpg"}) + "\n")
        f.write(json.dumps({"id": "img2", "thumb_original_url": "http://example.com/2.jpg"}) + "\n")
        f.write(json.dumps({"__complete__": True}) + "\n")

    reader = MetadataReader(metadata_file)

    assert reader.is_complete


def test_metadata_reader_many_lines(tmp_path):
    """Test completion check with more than 10 lines."""
    metadata_file = tmp_path / "metadata.jsonl"

    # Write more than 10 lines
    with open(metadata_file, "w") as f:
        for i in range(15):
            f.write(json.dumps({"id": f"img{i}"}) + "\n")
        f.write(json.dumps({"__complete__": True}) + "\n")

    reader = MetadataReader(metadata_file)
    assert reader.is_complete


def test_large_file_completion_reads_tail_only(tmp_path):
    """A large history is not scanned during a plain JSONL completion check."""
    from unittest.mock import patch

    metadata_file = tmp_path / "metadata.jsonl"
    metadata_file.write_bytes(b'{"id":"old"}\n' * 100_000 + b'{"__complete__":true}\n')
    reads = []
    original_open = open

    class TailOnly:
        def __enter__(self):
            self.file = original_open(metadata_file, "rb")
            return self

        def __exit__(self, *args):
            self.file.close()

        def seek(self, *args):
            return self.file.seek(*args)

        def tell(self):
            return self.file.tell()

        def read(self, size):
            reads.append(size)
            return self.file.read(size)

    with patch("mapillary_downloader.metadata_reader.open", return_value=TailOnly()):
        assert MetadataReader(metadata_file).is_complete
    assert sum(reads) == 65536


def test_completion_marker_outside_last_ten_lines_is_ignored(tmp_path):
    metadata_file = tmp_path / "metadata.jsonl"
    metadata_file.write_text('{"__complete__":true}\n' + '{"id":"later"}\n' * 10)
    assert not MetadataReader(metadata_file).is_complete
