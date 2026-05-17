"""Tests for Internet Archive stats formatting."""

from mapillary_downloader.ia_stats import format_stats


def test_format_stats_aligns_quality_rows():
    stats = {
        "total": {
            "collections": 30_115,
            "total_images": 615_177_869,
            "unique_images": 612_745_941,
            "bytes": 41_930_000_000_000,
        },
        "users": {"testuser"},
        "by_quality": {
            "original": {"collections": 510, "images": 430_399, "bytes": 319_470_000_000},
            "1024": {"collections": 28_095, "images": 582_473_499, "bytes": 34_380_000_000_000},
            "2048": {"collections": 1_506, "images": 32_268_148, "bytes": 7_230_000_000_000},
            "256": {"collections": 4, "images": 5_823, "bytes": 78_820_000},
        },
    }
    cache = {
        "mapillary-testuser-1024-webp": {
            "ia_collection": ["mapillary-images"],
        }
    }

    lines = format_stats(None, stats, cache).splitlines()

    assert "  original      510 collections        430,399 images (  0.022%)   319.47 GB" in lines
    assert "  1024       28,095 collections    582,473,499 images ( 29.124%)    34.38 TB" in lines
    assert "  2048        1,506 collections     32,268,148 images (  1.613%)     7.23 TB" in lines
    assert "  256             4 collections          5,823 images (  0.000%)    78.82 MB" in lines
