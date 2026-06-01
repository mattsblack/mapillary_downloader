"""WebP image conversion utilities (Pillow-based, in-process)."""

import io
import logging
from pathlib import Path

from PIL import Image, features

logger = logging.getLogger("mapillary_downloader")

# Quality/speed trade-offs for the libwebp encoder used by Pillow.
# quality: 0-100 (higher is better/larger). method: 0 (fast) - 6 (slow/best).
DEFAULT_WEBP_QUALITY = 80
DEFAULT_WEBP_METHOD = 4


def check_webp_available():
    """Check if Pillow was built with WebP support.

    Returns:
        bool: True if WebP encoding is available, False otherwise
    """
    try:
        return features.check("webp")
    except Exception:
        return False


def encode_webp(
    jpeg_bytes,
    output_path,
    *,
    exif=None,
    xmp=None,
    quality=DEFAULT_WEBP_QUALITY,
    method=DEFAULT_WEBP_METHOD,
):
    """Encode in-memory JPEG bytes to a WebP file, preserving metadata.

    This runs entirely in-process (no subprocess), and Pillow releases the GIL
    during the libwebp encode so it parallelises across threads.

    Args:
        jpeg_bytes: Raw JPEG image bytes
        output_path: Destination path for the WebP file
        exif: Optional EXIF bytes (as produced by piexif.dump) to embed
        xmp: Optional XMP packet bytes to embed
        quality: WebP quality (0-100)
        method: WebP encode method (0=fast, 6=slow/best)

    Returns:
        Path to the WebP file, or None if encoding failed
    """
    webp_path = Path(output_path)
    webp_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with Image.open(io.BytesIO(jpeg_bytes)) as img:
            img.load()

            save_kwargs = {"quality": quality, "method": method}

            # Preserve EXIF: prefer caller-provided (merged) EXIF, fall back to
            # whatever the source JPEG carried.
            exif_bytes = exif if exif is not None else img.info.get("exif")
            if exif_bytes:
                save_kwargs["exif"] = exif_bytes

            # Preserve XMP: prefer caller-provided packet, fall back to source.
            xmp_bytes = xmp if xmp is not None else img.info.get("xmp")
            if xmp_bytes:
                save_kwargs["xmp"] = xmp_bytes

            icc_profile = img.info.get("icc_profile")
            if icc_profile:
                save_kwargs["icc_profile"] = icc_profile

            img.save(webp_path, "WEBP", **save_kwargs)

        return webp_path

    except Exception as e:
        logger.error(f"Error encoding WebP to {webp_path}: {e}")
        return None


def convert_to_webp(
    jpg_path,
    output_path,
    *,
    quality=DEFAULT_WEBP_QUALITY,
    method=DEFAULT_WEBP_METHOD,
    delete_original=True,
):
    """Convert a JPG file to WebP, preserving embedded metadata.

    Args:
        jpg_path: Path to the JPG file
        output_path: Path for the WebP output
        quality: WebP quality (0-100)
        method: WebP encode method (0=fast, 6=slow/best)
        delete_original: Whether to delete the JPG after a successful conversion

    Returns:
        Path object to the new WebP file, or None if conversion failed
    """
    jpg_path = Path(jpg_path)

    try:
        jpeg_bytes = jpg_path.read_bytes()
    except Exception as e:
        logger.error(f"Error reading {jpg_path}: {e}")
        return None

    webp_path = encode_webp(jpeg_bytes, output_path, quality=quality, method=method)
    if webp_path is None:
        return None

    if delete_original:
        jpg_path.unlink()
    return webp_path
