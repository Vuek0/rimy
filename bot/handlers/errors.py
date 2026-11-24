"""Last resort: an error anywhere (a handler, the DB, Telegram) is logged and the user gets an answer,
instead of a button that silently does nothing."""

import logging

from aiogram.types import ErrorEvent

log = logging.getLogger(__name__)

ERROR_TEXT = "Ой, что-то пошло не так 😿 Попробуй ещё раз чуть позже."


async def on_error(event: ErrorEvent) -> bool:
    update = event.update
    log.error("update %s failed", update.update_id, exc_info=event.exception)
    try:
        if update.callback_query is not None:
            await update.callback_query.answer(ERROR_TEXT, show_alert=True)
        elif update.message is not None:
            await update.message.answer(ERROR_TEXT)
    except Exception:  # e.g. Telegram itself is unreachable: nothing more to do
        log.exception("could not tell the user about the error")
    return True  # handled: aiogram shouldn't log it again
