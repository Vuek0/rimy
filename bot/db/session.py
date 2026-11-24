import asyncio
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from bot.db.models import Base


BUSY_TIMEOUT_MS = 10_000  # a writer waits for the other one instead of failing with "database is locked"


def make_engine(url: str) -> AsyncEngine:
    parsed = make_url(url)
    is_file_sqlite = parsed.get_backend_name() == "sqlite" and parsed.database and parsed.database != ":memory:"
    if is_file_sqlite:
        folder = os.path.dirname(parsed.database)
        if folder:
            os.makedirs(folder, exist_ok=True)
    engine = create_async_engine(url)
    if is_file_sqlite:
        event.listen(engine.sync_engine, "connect", _sqlite_pragmas)
    return engine


def _sqlite_pragmas(dbapi_connection, _record) -> None:
    """The bot and the Mini App API write to one SQLite file at the same time.
    WAL lets readers work while someone writes; busy_timeout makes a second writer wait, not crash."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    cursor.execute("PRAGMA synchronous=NORMAL")  # safe with WAL, much faster commits
    cursor.close()


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    """Create tables directly (tests only; the bot uses Alembic migrations)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


ROOT = Path(__file__).resolve().parents[2]


def alembic_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def check_sqlite_writable(url: str) -> None:
    """SQLite writes a journal next to the database: the FOLDER must be writable, not only the file.
    Fail at startup with a clear message instead of buttons that silently do nothing."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite" or not parsed.database or parsed.database == ":memory:":
        return
    folder = os.path.dirname(os.path.abspath(parsed.database)) or "."
    probe = os.path.join(folder, ".write-test")
    try:
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
    except OSError as exc:
        raise RuntimeError(
            f"database folder {folder} is not writable ({exc}). In Docker, give the bot user the volume: "
            "docker run --rm -v rimy_rimy-data:/data alpine chown -R 1000:1000 /data"
        ) from exc


async def run_migrations(url: str) -> None:
    """alembic upgrade head. Runs in a thread because Alembic's async env starts its own event loop."""
    make_engine(url)  # creates the SQLite folder if needed
    check_sqlite_writable(url)
    await asyncio.to_thread(command.upgrade, alembic_config(url), "head")
