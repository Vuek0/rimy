import asyncio
import contextlib
import logging
from collections.abc import Iterator
from pathlib import Path

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo

from bot.ai.service import build_ai
from bot.api.app import create_app
from bot.config import get_settings
from bot.db.session import make_engine, make_sessionmaker, run_migrations
from bot.handlers import all_routers
from bot.handlers.errors import on_error
from bot.images import arts, booru
from bot.jobs.scheduler import Scheduler
from bot.middlewares import DbMiddleware
from bot.persona.memory import ChatMemory
from bot.i18n import COMMANDS as I18N_COMMANDS
from bot.profile import set_profile

WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp" / "dist"  # built Mini App (npm run build)


class ApiServer(uvicorn.Server):
    """uvicorn without its own signal handlers: aiogram handles Ctrl+C / SIGTERM, then we stop the API."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield

    def install_signal_handlers(self) -> None:  # older uvicorn versions
        pass

COMMANDS = [
    BotCommand(command="app", description="Открыть приложение"),
    BotCommand(command="review", description="Повторить карточки"),
    BotCommand(command="list", description="Мои слова"),
    BotCommand(command="stats", description="Статистика"),
    BotCommand(command="premium", description="Premium без лимитов"),
    BotCommand(command="promo", description="Ввести промокод"),
    BotCommand(command="practice", description="Разговорная практика вкл/выкл"),
    BotCommand(command="lang", description="Сменить изучаемый язык"),
    BotCommand(command="base", description="Язык общения с ботом"),
    BotCommand(command="delete", description="Удалить слово"),
    BotCommand(command="remind", description="Напоминания"),
    BotCommand(command="memory", description="Что Rimy помнит обо мне"),
    BotCommand(command="help", description="Помощь"),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    arts.STYLE = settings.reaction_style
    booru.configure(settings.danbooru_login, settings.danbooru_api_key)

    await run_migrations(settings.database_url)
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(DbMiddleware(sessionmaker, settings))
    dp.include_routers(*all_routers())
    dp.errors.register(on_error)  # no silent failures: log + tell the user

    await bot.set_my_commands(COMMANDS)
    for code in ("uz", "en"):  # the "/" menu in the user's Telegram language
        await bot.set_my_commands(
            [BotCommand(command=c, description=d) for c, d in I18N_COMMANDS[code]], language_code=code
        )
    await set_profile(bot)  # "What can this bot do?" and the profile text, in ru / uz / en
    if settings.webapp_url:  # the button next to the input field opens the Mini App
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Приложение", web_app=WebAppInfo(url=settings.webapp_url))
        )
    try:
        ai = build_ai(settings)
        scheduler = Scheduler(bot, sessionmaker, ai, settings)
        jobs = asyncio.create_task(scheduler.run())  # reminders, "I miss you", daily backup
        # The Mini App's API (and its static files) in the same event loop as the bot
        api = create_app(settings, sessionmaker, ai, bot, static_dir=WEBAPP_DIR)
        server = ApiServer(uvicorn.Config(api, host=settings.api_host, port=settings.api_port, log_level="info"))
        api_task = asyncio.create_task(server.serve())
        try:
            await dp.start_polling(bot, ai=ai, memory=ChatMemory(), scheduler=scheduler)
        finally:
            server.should_exit = True
            jobs.cancel()
            await api_task
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Bot stopped")
