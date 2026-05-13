# State Files

These filenames and directory names are durable operational state. Existing
archives, resumed jobs, and scraped discovery caches depend on them. Refactors
should centralize these names, but must not rename them without a compatibility
path.

## Collection State

- `mapillary-{username}-{quality}[-webp]/` - staging and final collection name.
- `metadata.jsonl` - uncompressed metadata cache while downloading.
- `metadata.jsonl.gz` - compressed metadata after finalization.
- `progress.json` - per-quality downloaded image IDs.
- `.api_cursor` - API pagination resume cursor.
- `__ia_thumb__.jpg` - Internet Archive item thumbnail.
- `download.log.{timestamp}` - per-run collection log.

## Discovery Caches

All discovery caches live under the `mapillary_downloader` XDG cache directory.

- `planet-latest_geonames.tsv.gz` - cached OSMNames dump.
- `locations.tsv` - location query variants.
- `locations.json` - scraped Mapillary location IDs.
- `leaderboards.json` - scraped Mapillary location leaderboards.
- `.stats.json` - cached archive.org collection statistics.

The discovery files are intentionally reused between runs to avoid repeating
large scraping jobs.
