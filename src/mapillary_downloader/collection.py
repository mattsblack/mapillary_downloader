"""Collection naming and path helpers.

The collection name format is stable archive state:
``mapillary-{username}-{quality}[-webp]``.
"""

from dataclasses import dataclass
from pathlib import Path
import re

from mapillary_downloader import paths

QUALITY_PATTERN = r"256|1024|2048|original"


@dataclass(frozen=True)
class CollectionId:
    """Stable Mapillary archive collection identity."""

    username: str
    quality: str
    is_webp: bool = False

    @property
    def name(self):
        """Return the stable collection directory/item name."""
        suffix = "-webp" if self.is_webp else ""
        return f"mapillary-{self.username}-{self.quality}{suffix}"

    @classmethod
    def parse(cls, name):
        """Parse a collection identifier or path, returning None on mismatch."""
        basename = Path(name).name
        match = re.match(rf"mapillary-(.+)-({QUALITY_PATTERN})(?:-webp)?$", basename)
        if not match:
            return None
        return cls(
            username=match.group(1),
            quality=match.group(2),
            is_webp=basename.endswith("-webp"),
        )


@dataclass(frozen=True)
class CollectionPaths:
    """Filesystem paths for staging and final collection state."""

    staging_dir: Path
    final_dir: Path

    @classmethod
    def for_collection(cls, output_dir, collection_id, cache_dir):
        """Build paths for a named collection without changing legacy layout."""
        output_dir = Path(output_dir)
        return cls(
            staging_dir=Path(cache_dir) / collection_id.name,
            final_dir=output_dir / collection_id.name,
        )

    @classmethod
    def anonymous(cls, output_dir, cache_dir):
        """Build paths for legacy anonymous downloader initialization."""
        return cls(
            staging_dir=Path(cache_dir) / paths.STAGING_DOWNLOAD_DIR,
            final_dir=Path(output_dir),
        )

    @property
    def metadata_file(self):
        return self.staging_dir / paths.METADATA_JSONL

    @property
    def compressed_metadata_file(self):
        return self.staging_dir / paths.METADATA_JSONL_GZ

    @property
    def progress_file(self):
        return self.staging_dir / paths.PROGRESS_JSON

    @property
    def cursor_file(self):
        return self.staging_dir / paths.API_CURSOR
