"""Transactional incremental progress and metadata resume checkpoints."""

import json
import sqlite3
from contextlib import closing, contextmanager


class ProgressStore:
    """Keep completed IDs, retry metadata, and a read offset in one transaction.

    JSON progress is imported once for compatibility, and remains the portable
    export format. The SQLite checkpoint avoids rewriting all IDs periodically.
    Connections are short lived so finalization can safely move collection files.
    """

    def __init__(self, path, quality):
        self.path = path
        self.quality = str(quality)

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                yield connection

    def load(self, legacy_file):
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS completed (
                    quality TEXT, image_id TEXT, PRIMARY KEY (quality, image_id)
                );
                CREATE TABLE IF NOT EXISTS checkpoint (
                    quality TEXT PRIMARY KEY, device INTEGER, inode INTEGER, offset INTEGER
                );
                CREATE TABLE IF NOT EXISTS retries (
                    quality TEXT, image_id TEXT, metadata TEXT, PRIMARY KEY (quality, image_id)
                );
            """)
            initialized = db.execute("SELECT 1 FROM checkpoint WHERE quality = ?", (self.quality,)).fetchone()
            if not initialized:
                legacy = json.loads(legacy_file.read_text()) if legacy_file.exists() else {}
                db.executemany(
                    "INSERT OR IGNORE INTO completed VALUES (?, ?)",
                    ((self.quality, image_id) for image_id in legacy.get(self.quality, [])),
                )
                db.execute("INSERT INTO checkpoint VALUES (?, NULL, NULL, 0)", (self.quality,))
            completed = {
                row[0] for row in db.execute("SELECT image_id FROM completed WHERE quality = ?", (self.quality,))
            }
            retries = {
                row[0]: json.loads(row[1])
                for row in db.execute("SELECT image_id, metadata FROM retries WHERE quality = ?", (self.quality,))
            }
        return completed, retries

    def resume_offset(self, metadata_file):
        if not metadata_file.exists():
            return 0
        stat = metadata_file.stat()
        with self.connection() as db:
            row = db.execute(
                "SELECT device, inode, offset FROM checkpoint WHERE quality = ?", (self.quality,)
            ).fetchone()
        if row and row[:2] == (stat.st_dev, stat.st_ino) and 0 <= row[2] <= stat.st_size:
            return row[2]
        return 0

    def save(self, completed, retries, metadata_file, offset):
        stat = metadata_file.stat() if metadata_file.exists() else None
        with self.connection() as db:
            db.executemany(
                "INSERT OR IGNORE INTO completed VALUES (?, ?)",
                ((self.quality, image_id) for image_id in completed),
            )
            db.execute("DELETE FROM retries WHERE quality = ?", (self.quality,))
            db.executemany(
                "INSERT INTO retries VALUES (?, ?, ?)",
                ((self.quality, image_id, json.dumps(image)) for image_id, image in retries.items()),
            )
            db.execute(
                "UPDATE checkpoint SET device = ?, inode = ?, offset = ? WHERE quality = ?",
                (stat.st_dev if stat else None, stat.st_ino if stat else None, offset, self.quality),
            )
