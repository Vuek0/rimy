import asyncio
import os

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from bot.db.models import Base

config = context.config
target_metadata = Base.metadata


def get_url() -> str:
    # Explicit URL from run_migrations() wins; for the `alembic` CLI fall back to DATABASE_URL, then alembic.ini.
    url = config.get_main_option("sqlalchemy.url")
    if config.cmd_opts is not None:  # running from the CLI
        url = os.environ.get("DATABASE_URL", url)
    return url or ""


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite can't ALTER most things; batch mode recreates tables safely
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(get_url())
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=get_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_async_migrations())
