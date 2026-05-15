"""Chunk manifest helpers for capped download batches."""

import json

from mapillary_downloader import paths
from mapillary_downloader.utils import safe_json_save


class ChunkManifest:
    """Persistent manifest for chunked collection output."""

    def __init__(self, path, collection_id, *, bbox=None, max_size_bytes=None, max_images=None):
        self.path = path
        self.collection_id = collection_id
        self.expected = {
            "username": collection_id.username,
            "quality": collection_id.quality,
            "is_webp": collection_id.is_webp,
            "bbox": bbox,
        }
        self.limits = {
            "max_size_bytes": max_size_bytes,
            "max_images": max_images,
        }
        self.data = self._load()

    def _load(self):
        if self.path.exists():
            with open(self.path) as f:
                data = json.load(f)
            params = data.get("params", {})
            for key, value in self.expected.items():
                if params.get(key) != value:
                    raise ValueError(
                        f"Cached chunk job was created with {key}={params.get(key)!r}; current value is {value!r}"
                    )
            return data

        return {
            "mode": "chunked",
            "params": self.expected,
            "limits": self.limits,
            "next_chunk": 1,
            "completed": [],
        }

    @classmethod
    def for_paths(cls, collection_paths, collection_id, **kwargs):
        return cls(collection_paths.chunks_file, collection_id, **kwargs)

    @property
    def next_chunk(self):
        return int(self.data.get("next_chunk", 1))

    @property
    def is_complete(self):
        return any(entry.get("final") for entry in self.data.get("completed", []))

    @property
    def finalizing(self):
        return self.data.get("finalizing")

    def next_name(self):
        return self.collection_id.chunk_name(self.next_chunk)

    def next_output_dir(self, output_base_dir):
        return output_base_dir / self.next_name()

    def advance(self):
        self.data["next_chunk"] = self.next_chunk + 1
        self.save()

    def mark_finalizing(self, name, images=0, bytes_count=0, final=False):
        self.data["finalizing"] = {
            "name": name,
            "images": images,
            "bytes": bytes_count,
            "final": final,
        }
        self.save()

    def clear_finalizing(self):
        self.data.pop("finalizing", None)
        self.save()

    def mark_completed(self, name, images, bytes_count, final=False):
        self.data.setdefault("completed", []).append(
            {
                "name": name,
                "images": images,
                "bytes": bytes_count,
                "final": final,
            }
        )
        self.data.pop("finalizing", None)
        self.data["next_chunk"] = self.next_chunk + 1
        self.save()

    def save(self):
        safe_json_save(self.path, self.data)


def is_chunk_metadata_name(name):
    """Return True for chunk manifest metadata names."""
    return name == paths.CHUNKS_JSON
