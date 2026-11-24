"""Short-term memory in RAM (long-term memory comes in a later stage):
- the last messages of the chat with the persona;
- for ➕ buttons under persona replies: what each word meant in that reply.
"""

import time
from collections import OrderedDict, defaultdict, deque
from datetime import datetime

MAX_MESSAGES = 12
MAX_REMEMBERED_REPLIES = 200
CONVERSATION_WINDOW = 15 * 60  # seconds after the persona's last reply when we're "still talking"
ANSWER_WINDOW = 10 * 60  # a shown review card accepts a typed/spoken answer for this long


class ChatMemory:
    def __init__(self, max_messages: int = MAX_MESSAGES):
        self._history: dict[int, deque[dict[str, str]]] = defaultdict(lambda: deque(maxlen=max_messages))
        self._word_hints: OrderedDict[tuple[int, int], tuple[dict[str, str], str]] = OrderedDict()
        self._last_reply_at: dict[int, float] = {}
        self._loaded: set[int] = set()  # users whose history was loaded from the DB after a restart
        self._previous_active: dict[int, datetime | None] = {}
        self._waiting: dict[int, tuple[int, int, int, float]] = {}

    # --- persistence: the DB keeps the history across restarts and deploys ---

    def needs_loading(self, user_id: int) -> bool:
        return user_id not in self._loaded

    def load(self, user_id: int, messages: list[dict[str, str]]) -> None:
        """Fill from the DB once per process (without opening a "conversation" window)."""
        self._loaded.add(user_id)
        history = self._history[user_id]
        history.clear()
        history.extend(messages[-(history.maxlen or len(messages)):])

    # --- when was the user active before this message (for the persona's mood) ---

    def set_previous_active(self, user_id: int, when: "datetime | None") -> None:
        self._previous_active[user_id] = when

    def previous_active(self, user_id: int) -> "datetime | None":
        return self._previous_active.get(user_id)

    def history(self, user_id: int) -> list[dict[str, str]]:
        return list(self._history[user_id])

    def add(self, user_id: int, role: str, content: str) -> None:
        self._history[user_id].append({"role": role, "content": content})
        if role == "assistant":
            self._last_reply_at[user_id] = time.monotonic()

    def clear(self, user_id: int) -> None:
        self._history.pop(user_id, None)
        self._last_reply_at.pop(user_id, None)

    def last_reply(self, user_id: int) -> str:
        """The persona's latest message, or "" if none."""
        for message in reversed(self._history[user_id]):
            if message["role"] == "assistant":
                return message["content"]
        return ""

    def in_conversation(self, user_id: int, window: float = CONVERSATION_WINDOW) -> bool:
        """Did the persona talk to this user recently? Then short messages are probably answers, not words."""
        last = self._last_reply_at.get(user_id)
        return last is not None and time.monotonic() - last < window

    # --- a review card waiting for a typed or spoken answer ---

    def await_answer(self, user_id: int, card_id: int, chat_id: int, message_id: int) -> None:
        self._waiting[user_id] = (card_id, chat_id, message_id, time.monotonic())

    def waiting_answer(self, user_id: int, window: float = ANSWER_WINDOW) -> tuple[int, int, int] | None:
        """(card_id, chat_id, message_id) of the card shown last, if it's still waiting for an answer."""
        waiting = self._waiting.get(user_id)
        if waiting is None or time.monotonic() - waiting[3] > window:
            return None
        return waiting[:3]

    def stop_waiting(self, user_id: int) -> None:
        self._waiting.pop(user_id, None)

    def end_conversation(self, user_id: int) -> None:
        """The user switched to adding words: keep the history, but stop treating messages as answers."""
        self._last_reply_at.pop(user_id, None)

    def knows(self, user_id: int, text: str) -> bool:
        return any(m["content"] == text for m in self._history[user_id])

    def remember_words(self, chat_id: int, message_id: int, meanings: dict[str, str], context: str) -> None:
        if not meanings:
            return
        self._word_hints[(chat_id, message_id)] = (meanings, context)
        while len(self._word_hints) > MAX_REMEMBERED_REPLIES:
            self._word_hints.popitem(last=False)

    def word_hint(self, chat_id: int, message_id: int, word: str) -> tuple[str, str]:
        """(meaning in that reply, the reply text) - empty strings if forgotten (e.g. after a restart)."""
        meanings, context = self._word_hints.get((chat_id, message_id), ({}, ""))
        return meanings.get(word, ""), context if word in meanings else ""
