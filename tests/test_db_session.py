"""SQLite settings for concurrent writers (the bot and the Mini App API share one file)."""

import asyncio

from sqlalchemy import text

from bot.db.repo import Repo
from bot.db.session import BUSY_TIMEOUT_MS, init_db, make_engine, make_sessionmaker


async def test_file_sqlite_uses_wal_and_waits_for_locks(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{(tmp_path / 'bot.db').as_posix()}")
    async with engine.connect() as conn:
        assert (await conn.execute(text("PRAGMA journal_mode"))).scalar() == "wal"
        assert (await conn.execute(text("PRAGMA busy_timeout"))).scalar() == BUSY_TIMEOUT_MS
    await init_db(engine)

    # two sessions writing at once (a chat update and an API request) both succeed
    sessionmaker = make_sessionmaker(engine)

    async def add_user(user_id: int) -> None:
        async with sessionmaker() as session:
            await Repo(session).ensure_user(user_id, native_lang="ru", timezone="Asia/Tashkent", target_lang="it")
            await session.commit()

    await asyncio.gather(*(add_user(i) for i in range(1, 11)))
    async with sessionmaker() as session:
        assert await Repo(session).count_users() == 10
    await engine.dispose()
