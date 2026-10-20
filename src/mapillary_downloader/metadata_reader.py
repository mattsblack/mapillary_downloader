"""Streaming metadata reader with filtering."""

import gzip
import json
import logging
from collections import deque
from pathlib import Path

logger = logging.getLogger("mapillary_downloader")


class MetadataReader:
    """Streams metadata.jsonl line-by-line with filtering.

    This avoids loading millions of image dicts into memory.
    """

    COMPLETION_MARKER = {"__complete__": True}

    def __init__(self, metadata_file):
        """Initialize metadata reader.

        Args:
            metadata_file: Path to metadata.jsonl or metadata.jsonl.gz
        """
        self.metadata_file = Path(metadata_file)
        self.is_complete = self._check_complete()

    def _check_complete(self):
        """Check if metadata file has completion marker.

        Returns:
            True if completion marker found, False otherwise
        """
        if not self.metadata_file.exists():
            return False

        # Check last few lines for completion marker (it should be at the end)
        try:
            if self.metadata_file.suffix == ".gz":
                # Gzip is not independently seekable; keep the streaming path.
                with gzip.open(self.metadata_file, "rt") as f:
                    lines = deque(f, maxlen=10)
            else:
                with open(self.metadata_file, "rb") as f:
                    f.seek(0, 2)
                    position = f.tell()
                    tail = b""
                    while position > 0 and len(tail.splitlines()) < 11:
                        size = min(position, 65536)
                        position -= size
                        f.seek(position)
                        tail = f.read(size) + tail
                    lines = tail.splitlines()[-10:]

            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("__complete__"):
                        return True
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

            return False
        except Exception:
            return False

    @staticmethod
    def mark_complete(metadata_file):
        """Append completion marker to metadata file.

        Args:
            metadata_file: Path to metadata.jsonl
        """
        metadata_file = Path(metadata_file)
        if metadata_file.exists():
            with open(metadata_file, "a") as f:
                f.write(json.dumps(MetadataReader.COMPLETION_MARKER) + "\n")
                f.flush()
            logger.info("Marked metadata file as complete")
