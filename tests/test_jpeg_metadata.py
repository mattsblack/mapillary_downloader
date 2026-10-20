"""Single-write JPEG preparation preserves metadata and compressed pixels."""

import io
from unittest.mock import Mock, patch

import piexif
import pytest
from PIL import Image

from mapillary_downloader.jpeg_metadata import insert_metadata
from mapillary_downloader.worker import download_and_prepare
from mapillary_downloader.xmp_writer import XMP_NAMESPACE


def source_jpeg():
    output = io.BytesIO()
    exif = piexif.dump({"0th": {piexif.ImageIFD.Orientation: 6, piexif.ImageIFD.Make: b"Original"}})
    Image.new("RGB", (64, 32), "green").save(output, "JPEG", exif=exif, icc_profile=b"test-profile")
    return output.getvalue()


def test_worker_preserves_pixels_camera_tags_and_embeds_panorama(tmp_path):
    source = source_jpeg()
    source = insert_metadata(source, xmp=b"old-xmp")
    metadata = {
        "id": "image",
        "thumb_original_url": "https://example.invalid/image",
        "captured_at": 1700000000000,
        "is_pano": True,
        "width": 64,
        "height": 32,
        "geometry": {"coordinates": [-1, 50]},
    }
    session = Mock()
    session.get.return_value.content = source

    def write_once(path, data):
        with open(path, "wb") as output:
            return output.write(data)

    with patch("pathlib.Path.write_bytes", autospec=True, side_effect=write_once) as write:
        kind, result = download_and_prepare((metadata, tmp_path, "original", False, "token", 80, 0), session)
        write.assert_called_once()
        path, prepared = write.call_args.args
    assert kind == "result" and result[4], result
    saved = path.read_bytes()
    assert prepared == saved
    assert path.stat().st_mtime == metadata["captured_at"] / 1000
    assert saved.count(XMP_NAMESPACE) == 1
    assert b"old-xmp" not in saved
    tags = piexif.load(saved)
    assert tags["0th"][piexif.ImageIFD.Orientation] == 6
    assert tags["0th"][piexif.ImageIFD.Make] == b"Original"
    assert tags["GPS"][piexif.GPSIFD.GPSLatitudeRef] == b"N"
    with Image.open(io.BytesIO(source)) as before, Image.open(io.BytesIO(saved)) as after:
        assert before.tobytes() == after.tobytes()
        assert after.info["icc_profile"] == b"test-profile"
        assert b"equirectangular" in after.info["xmp"]


def test_none_packets_preserve_existing_metadata():
    source = insert_metadata(source_jpeg(), xmp=b"existing")
    assert insert_metadata(source) == source


@pytest.mark.parametrize("data", [b"not-jpeg", b"\xff\xd8\xff\xe1\x00\x01", b"\xff\xd8\xff\xe1\xff\xff"])
def test_rejects_malformed_headers(data):
    with pytest.raises(ValueError):
        insert_metadata(data, xmp=b"new")
