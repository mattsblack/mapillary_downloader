"""Stage functions for the two-stage download/convert pipeline.

The pipeline is split into two cooperating stages so that network-bound work
and CPU-bound WebP encoding can each run at their own ideal concurrency:

- ``download_and_prepare`` runs in I/O-bound download workers. It fetches the
  image into memory and applies metadata. For the non-WebP path it writes the
  final JPEG itself; for the WebP path it returns a :class:`ConvertTask` for a
  CPU-bound converter to encode.
- ``convert_task`` runs in CPU-bound convert workers. It encodes the in-memory
  JPEG to WebP with Pillow (no subprocess, no intermediate temp file).
"""

import os
from collections import namedtuple
from datetime import datetime
from pathlib import Path

from mapillary_downloader.exif_writer import build_exif_bytes, write_exif_to_image
from mapillary_downloader.webp_converter import encode_webp
from mapillary_downloader.xmp_writer import build_xmp_bytes, write_xmp_to_image
from mapillary_downloader.utils import http_get_with_retry

# Work passed from the download stage to the convert stage.
ConvertTask = namedtuple(
    "ConvertTask",
    [
        "image_id",
        "sequence_id",
        "bytes_downloaded",
        "jpeg_bytes",
        "exif_bytes",
        "xmp_bytes",
        "final_path",
        "mtime",
        "quality",
        "method",
    ],
)


def _image_dir(output_dir, image_data):
    """Resolve the per-image output directory (organized by capture date)."""
    output_dir = Path(output_dir)
    sequence_id = image_data.get("sequence")

    captured_at = image_data.get("captured_at")
    if captured_at:
        date_str = datetime.utcfromtimestamp(captured_at / 1000).strftime("%Y-%m-%d")
    else:
        date_str = "unknown-date"

    if sequence_id:
        img_dir = output_dir / date_str / sequence_id
    else:
        img_dir = output_dir / date_str
    img_dir.mkdir(parents=True, exist_ok=True)
    return img_dir, sequence_id


def download_and_prepare(work_item, session):
    """Download an image and apply metadata (runs in a download worker).

    Args:
        work_item: Tuple of
            (image_data, output_dir, quality, convert_webp, access_token,
             webp_quality, webp_method)
        session: requests.Session reused by this worker

    Returns:
        Tuple of (kind, payload):
          - ("result", result_tuple) when the image is fully handled (failure,
            or a JPEG written directly for the non-WebP path)
          - ("convert", ConvertTask) when WebP encoding still needs to happen
    """
    image_data, output_dir, quality, convert_webp, access_token, webp_quality, webp_method = work_item

    image_id = image_data["id"]
    quality_field = f"thumb_{quality}_url"
    sequence_id = image_data.get("sequence")

    try:
        image_url = image_data.get(quality_field)
        if not image_url:
            return "result", (image_id, 0, 0, sequence_id, False, f"No {quality} URL")

        img_dir, sequence_id = _image_dir(output_dir, image_data)

        session.headers.update({"Authorization": f"OAuth {access_token}"})

        try:
            response = http_get_with_retry(session, image_url, max_retries=3, base_delay=1.0, timeout=60)
            jpeg_bytes = response.content
        except Exception as e:
            return "result", (image_id, 0, 0, sequence_id, False, f"Download failed: {e}")

        bytes_downloaded = len(jpeg_bytes)

        mtime = None
        if "captured_at" in image_data:
            mtime = image_data["captured_at"] / 1000

        if convert_webp:
            exif_bytes = build_exif_bytes(image_data, source_bytes=jpeg_bytes)
            xmp_bytes = build_xmp_bytes(image_data)
            final_path = img_dir / f"{image_id}.webp"
            task = ConvertTask(
                image_id=image_id,
                sequence_id=sequence_id,
                bytes_downloaded=bytes_downloaded,
                jpeg_bytes=jpeg_bytes,
                exif_bytes=exif_bytes,
                xmp_bytes=xmp_bytes,
                final_path=final_path,
                mtime=mtime,
                quality=webp_quality,
                method=webp_method,
            )
            return "convert", task

        # Non-WebP path: write the JPEG and its metadata directly.
        final_path = img_dir / f"{image_id}.jpg"
        with open(final_path, "wb") as f:
            f.write(jpeg_bytes)

        write_exif_to_image(final_path, image_data)
        write_xmp_to_image(final_path, image_data)

        if mtime is not None:
            os.utime(final_path, (mtime, mtime))

        output_bytes = final_path.stat().st_size if final_path.exists() else bytes_downloaded
        return "result", (image_id, bytes_downloaded, output_bytes, sequence_id, True, None)

    except Exception as e:
        return "result", (image_id, 0, 0, sequence_id, False, str(e))


def convert_task(task):
    """Encode a prepared image to WebP (runs in a convert worker).

    Args:
        task: ConvertTask produced by :func:`download_and_prepare`

    Returns:
        Result tuple
        (image_id, bytes_downloaded, output_bytes, sequence_id, success, error)
    """
    try:
        webp_path = encode_webp(
            task.jpeg_bytes,
            task.final_path,
            exif=task.exif_bytes,
            xmp=task.xmp_bytes,
            quality=task.quality,
            method=task.method,
        )
        if webp_path is None:
            return (task.image_id, task.bytes_downloaded, 0, task.sequence_id, False, "WebP conversion failed")

        if task.mtime is not None:
            os.utime(webp_path, (task.mtime, task.mtime))

        output_bytes = webp_path.stat().st_size if webp_path.exists() else task.bytes_downloaded
        return (task.image_id, task.bytes_downloaded, output_bytes, task.sequence_id, True, None)

    except Exception as e:
        return (task.image_id, task.bytes_downloaded, 0, task.sequence_id, False, str(e))
