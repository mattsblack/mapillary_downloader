"""Tests for Pillow-based WebP conversion."""

import io

from PIL import Image

from mapillary_downloader.webp_converter import (
    check_webp_available,
    convert_to_webp,
    encode_webp,
)


def _jpeg_bytes(size=(64, 48), color="red"):
    """Return a small in-memory JPEG for tests."""
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, "JPEG")
    return buf.getvalue()


def test_check_webp_available():
    """Pillow in the test environment should support WebP."""
    assert check_webp_available() is True


def test_encode_webp_success(tmp_path):
    """encode_webp writes a valid WebP file from in-memory JPEG bytes."""
    webp_output = tmp_path / "test.webp"

    result = encode_webp(_jpeg_bytes(), webp_output)

    assert result == webp_output
    assert webp_output.exists()
    with Image.open(webp_output) as img:
        assert img.format == "WEBP"


def test_encode_webp_creates_parent_dirs(tmp_path):
    """Output directory is created if needed."""
    webp_output = tmp_path / "nested" / "dir" / "test.webp"

    encode_webp(_jpeg_bytes(), webp_output)

    assert webp_output.exists()


def test_encode_webp_failure_returns_none(tmp_path):
    """Invalid image bytes yield None instead of raising."""
    webp_output = tmp_path / "bad.webp"

    result = encode_webp(b"not a real image", webp_output)

    assert result is None
    assert not webp_output.exists()


def test_encode_webp_embeds_xmp(tmp_path):
    """XMP bytes passed to encode_webp are embedded in the output."""
    webp_output = tmp_path / "pano.webp"
    xmp = b'<x:xmpmeta xmlns:x="adobe:ns:meta/">marker-equirectangular</x:xmpmeta>'

    encode_webp(_jpeg_bytes(), webp_output, xmp=xmp)

    with Image.open(webp_output) as img:
        assert b"marker-equirectangular" in img.info.get("xmp", b"")


def test_convert_to_webp_success(tmp_path):
    """convert_to_webp converts a JPG file and removes the original."""
    jpg_path = tmp_path / "test.jpg"
    jpg_path.write_bytes(_jpeg_bytes())
    webp_output = tmp_path / "test.webp"

    webp_path = convert_to_webp(jpg_path, webp_output)

    assert webp_path == webp_output
    assert webp_output.exists()
    assert not jpg_path.exists()  # Original should be deleted


def test_convert_to_webp_keeps_original_when_requested(tmp_path):
    """delete_original=False leaves the source JPG in place."""
    jpg_path = tmp_path / "test.jpg"
    jpg_path.write_bytes(_jpeg_bytes())
    webp_output = tmp_path / "test.webp"

    convert_to_webp(jpg_path, webp_output, delete_original=False)

    assert webp_output.exists()
    assert jpg_path.exists()


def test_convert_to_webp_failure(tmp_path):
    """A non-image file fails conversion and keeps the original."""
    jpg_path = tmp_path / "test.jpg"
    jpg_path.write_bytes(b"fake jpg data")
    webp_output = tmp_path / "test.webp"

    webp_path = convert_to_webp(jpg_path, webp_output)

    assert webp_path is None
    assert jpg_path.exists()  # Original should still exist on failure


def test_convert_to_webp_missing_file(tmp_path):
    """A missing source file returns None instead of raising."""
    jpg_path = tmp_path / "nope.jpg"
    webp_output = tmp_path / "test.webp"

    assert convert_to_webp(jpg_path, webp_output) is None
