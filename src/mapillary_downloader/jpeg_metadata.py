"""Attach EXIF and XMP without decoding pixels or rewriting files."""

from mapillary_downloader.xmp_writer import XMP_NAMESPACE


def insert_metadata(jpeg, *, exif=None, xmp=None):
    """Replace selected APP1 packets, preserving all other JPEG segments.

    A None packet preserves the corresponding source metadata. Only JPEG
    headers are inspected; compressed scan data is copied unchanged.
    """
    if not jpeg.startswith(b"\xff\xd8"):
        raise ValueError("Not a JPEG image")

    packets = []
    for packet in (exif, XMP_NAMESPACE + xmp if xmp is not None else None):
        if packet is not None:
            length = len(packet) + 2
            if length > 65535:
                raise ValueError("JPEG metadata packet exceeds APP1 capacity")
            packets.append(b"\xff\xe1" + length.to_bytes(2, "big") + packet)

    headers = []
    pos = 2
    while pos < len(jpeg):
        start = pos
        if jpeg[pos] != 0xFF:
            raise ValueError("Invalid JPEG header")
        while pos < len(jpeg) and jpeg[pos] == 0xFF:
            pos += 1
        if pos >= len(jpeg):
            raise ValueError("Truncated JPEG marker")
        marker = jpeg[pos]
        pos += 1
        if marker in (0xDA, 0xD9):
            pos = start
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            headers.append(jpeg[start:pos])
            continue
        if pos + 2 > len(jpeg):
            raise ValueError("Truncated JPEG segment")
        length = int.from_bytes(jpeg[pos : pos + 2], "big")
        end = pos + length
        if length < 2 or end > len(jpeg):
            raise ValueError("Invalid JPEG segment length")
        payload = jpeg[pos + 2 : end]
        replace = marker == 0xE1 and (
            (exif is not None and payload.startswith(b"Exif\x00\x00"))
            or (xmp is not None and payload.startswith(XMP_NAMESPACE))
        )
        if not replace:
            headers.append(jpeg[start:end])
        pos = end

    # Retain JFIF APP0 as the first segment when present.
    prefix = [b"\xff\xd8"]
    if headers and headers[0].startswith(b"\xff\xe0"):
        prefix.append(headers.pop(0))
    return b"".join(prefix + packets + headers + [jpeg[pos:]])
