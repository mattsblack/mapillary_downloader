"""Download limit parsing and state."""

from dataclasses import dataclass

SIZE_UNITS = {
    "B": 1,
    "KB": 1_000,
    "MB": 1_000_000,
    "GB": 1_000_000_000,
    "TB": 1_000_000_000_000,
    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
    "TIB": 1024**4,
}


def parse_size(value):
    """Parse sizes like 900GB, 1TB, 50GiB, or none."""
    if value is None:
        return None
    if isinstance(value, int):
        return value

    text = str(value).strip()
    if text.lower() in {"none", "off", "unlimited", "0"}:
        return None

    number = ""
    unit = ""
    for ch in text:
        if ch.isdigit() or ch == ".":
            number += ch
        elif not ch.isspace():
            unit += ch

    if not number:
        raise ValueError(f"Invalid size: {value}")

    unit = unit.upper() or "B"
    if unit not in SIZE_UNITS:
        raise ValueError(f"Invalid size unit: {unit}")

    return int(float(number) * SIZE_UNITS[unit])


@dataclass(frozen=True)
class DownloadLimits:
    """Download limits for one output batch."""

    max_size_bytes: int | None = 900_000_000_000
    min_free_space_bytes: int | None = 50_000_000_000
    max_images: int | None = None

    @property
    def is_chunked(self):
        return self.max_size_bytes is not None or self.max_images is not None
