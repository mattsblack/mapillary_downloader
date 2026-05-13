"""Stable state-file names and cache paths.

These names are part of the operational contract for existing archives and
scraped discovery caches. Keep changes additive and backwards compatible.
"""

from mapillary_downloader.utils import get_cache_dir

STAGING_DOWNLOAD_DIR = "download"

METADATA_JSONL = "metadata.jsonl"
METADATA_JSONL_GZ = "metadata.jsonl.gz"
PROGRESS_JSON = "progress.json"
API_CURSOR = ".api_cursor"
IA_THUMBNAIL = "__ia_thumb__.jpg"
CHUNKS_JSON = "chunks.json"
PAYLOAD_DIR = "payload"

STATS_CACHE_JSON = ".stats.json"
GEONAMES_TSV_GZ = "planet-latest_geonames.tsv.gz"
LOCATIONS_TSV = "locations.tsv"
LOCATIONS_JSON = "locations.json"
LEADERBOARDS_JSON = "leaderboards.json"

LOG_FILE_PREFIX = "download.log."


def cache_file(name):
    """Return a path inside the mapillary_downloader cache directory."""
    return get_cache_dir() / name
