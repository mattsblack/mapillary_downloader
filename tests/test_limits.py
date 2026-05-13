"""Tests for download limit parsing."""

from mapillary_downloader.limits import DownloadLimits, parse_size


def test_parse_size_decimal_units():
    assert parse_size("900GB") == 900_000_000_000
    assert parse_size("1TB") == 1_000_000_000_000


def test_parse_size_none_values():
    assert parse_size("none") is None
    assert parse_size("0") is None


def test_download_limits_chunked_when_limit_present():
    assert DownloadLimits(max_size_bytes=1).is_chunked
    assert not DownloadLimits(max_size_bytes=None, max_images=None).is_chunked
