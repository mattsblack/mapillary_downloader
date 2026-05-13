"""Finalize staged Mapillary collections into archive-ready output."""

import gzip
import logging
import shutil

from PIL import Image

from mapillary_downloader import paths
from mapillary_downloader.ia_meta import generate_ia_metadata
from mapillary_downloader.tar_sequences import tar_sequence_directories
from mapillary_downloader.utils import format_size

logger = logging.getLogger("mapillary_downloader")


def create_thumbnail(collection_dir, convert_webp):
    """Create a 256x256 JPEG thumbnail at the collection root for IA."""
    dest = collection_dir / paths.IA_THUMBNAIL
    ext = ".webp" if convert_webp else ".jpg"
    for path in collection_dir.rglob(f"*{ext}"):
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((256, 256))
            img.save(dest, "JPEG")
        logger.info("Thumbnail: %s", dest.name)
        return
    logger.warning("No images found for thumbnail")


def compress_metadata(collection_dir):
    """Gzip metadata.jsonl if present, preserving the existing output name."""
    metadata_file = collection_dir / paths.METADATA_JSONL
    if not metadata_file.exists():
        return

    original_size = metadata_file.stat().st_size
    if original_size <= 0:
        return

    logger.info("Compressing metadata.jsonl...")
    gzipped_file = collection_dir / paths.METADATA_JSONL_GZ

    with open(metadata_file, "rb") as f_in:
        with gzip.open(gzipped_file, "wb", compresslevel=9) as f_out:
            shutil.copyfileobj(f_in, f_out)

    compressed_size = gzipped_file.stat().st_size
    metadata_file.unlink()

    savings = 100 * (1 - compressed_size / original_size)
    logger.info(
        f"Compressed metadata: {format_size(original_size)} -> {format_size(compressed_size)} "
        f"({savings:.1f}% savings)"
    )


def finalize_collection(staging_dir, final_dir, *, convert_webp, tar_sequences, before_move=None):
    """Prepare a staged collection and move it to its final destination."""
    create_thumbnail(staging_dir, convert_webp)

    if tar_sequences:
        tar_sequence_directories(staging_dir)

    compress_metadata(staging_dir)
    generate_ia_metadata(staging_dir)

    if before_move:
        before_move()

    logger.info("Moving to final destination...")
    if final_dir.exists():
        logger.warning(f"Destination already exists, removing: {final_dir}")
        shutil.rmtree(final_dir)

    final_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staging_dir), str(final_dir))
    logger.info(f"Done: {final_dir}")
