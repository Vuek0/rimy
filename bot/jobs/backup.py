"""Daily backup of the SQLite database, sent to the owner in Telegram."""

import asyncio
import gzip
import os
import sqlite3
import tempfile

from sqlalchemy.engine import make_url


def sqlite_path(database_url: str) -> str | None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return url.database


def _snapshot(path: str) -> bytes:
    """A consistent copy even while the bot writes (SQLite online backup API), gzipped."""
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        src, dst = sqlite3.connect(path), sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        with open(tmp, "rb") as f:
            return gzip.compress(f.read(), compresslevel=9)
    finally:
        os.remove(tmp)


async def make_backup(database_url: str) -> bytes | None:
    """Gzipped DB snapshot, or None for non-SQLite databases (back those up with their own tools)."""
    path = sqlite_path(database_url)
    if path is None or not os.path.exists(path):
        return None
    return await asyncio.to_thread(_snapshot, path)
