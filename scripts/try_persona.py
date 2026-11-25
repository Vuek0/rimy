"""Ask the real AI chain like the bot would (no Telegram, no database), to check replies locally.

    python scripts/try_persona.py <native> <target> "<message>"      e.g.  uz fr "Salut, Rimi"

Uses the keys from .env; prints only the replies, never the keys.
"""

import asyncio
import sys

from bot.ai.service import build_ai
from bot.config import get_settings
from bot.persona.card import DEFAULT_CARD


async def main(native: str, target: str, text: str) -> None:
    ai = build_ai(get_settings())
    for i in range(3):  # a few tries: the model's wording varies
        reply = await ai.persona_reply(DEFAULT_CARD, [], text, target, native)
        print(f"--- try {i + 1} ---\n{reply.text}")
        for w in reply.words:
            print(f"  + {w.word} = {w.meaning}")


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:4]))
