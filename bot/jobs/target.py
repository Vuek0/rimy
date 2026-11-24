from types import SimpleNamespace

from aiogram import Bot


class ChatTarget:
    """Looks like a Message for code that "answers" (stickers, reactions), but writes to a chat directly.
    Lets background jobs reuse the same sending code as handlers."""

    def __init__(self, bot: Bot, chat_id: int):
        self.bot = bot
        self.chat = SimpleNamespace(id=chat_id)

    async def answer(self, text: str, **kwargs):
        return await self.bot.send_message(self.chat.id, text, **kwargs)

    async def answer_photo(self, photo, **kwargs):
        return await self.bot.send_photo(self.chat.id, photo, **kwargs)

    async def answer_sticker(self, sticker, **kwargs):
        return await self.bot.send_sticker(self.chat.id, sticker, **kwargs)

    async def answer_document(self, document, **kwargs):
        return await self.bot.send_document(self.chat.id, document, **kwargs)
