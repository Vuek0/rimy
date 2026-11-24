"""An error anywhere must reach the user, not leave a dead button."""

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.methods import AnswerCallbackQuery, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot.handlers.errors import ERROR_TEXT, on_error

USER = User(id=1, is_bot=False, first_name="U")
CHAT = Chat(id=1, type="private")


class RecordingBot(Bot):
    """Doesn't talk to Telegram: records the API calls instead."""

    def __init__(self):
        super().__init__("123:ABC")
        self.calls = []

    async def __call__(self, method, request_timeout=None):
        self.calls.append(method)
        return True


@pytest.fixture
def dispatcher():
    dp = Dispatcher()
    broken = Router()

    @broken.message()
    async def fail_message(message: Message):
        raise RuntimeError("attempt to write a readonly database")

    @broken.callback_query()
    async def fail_callback(callback: CallbackQuery):
        raise RuntimeError("attempt to write a readonly database")

    dp.include_router(broken)
    dp.errors.register(on_error)
    return dp


async def test_failed_button_shows_an_alert(dispatcher):
    bot = RecordingBot()
    message = Message(message_id=1, date=0, chat=CHAT, from_user=USER, text="x")
    update = Update(update_id=1, callback_query=CallbackQuery(
        id="q", from_user=USER, chat_instance="c", data="add:save", message=message))
    await dispatcher.feed_update(bot, update)
    answers = [c for c in bot.calls if isinstance(c, AnswerCallbackQuery)]
    assert answers and answers[0].text == ERROR_TEXT and answers[0].show_alert


async def test_failed_message_gets_a_reply(dispatcher):
    bot = RecordingBot()
    update = Update(update_id=2, message=Message(message_id=1, date=0, chat=CHAT, from_user=USER, text="hi"))
    await dispatcher.feed_update(bot, update)
    sent = [c for c in bot.calls if isinstance(c, SendMessage)]
    assert sent and sent[0].text == ERROR_TEXT
