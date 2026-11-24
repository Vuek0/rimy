"""Who is calling the API: Telegram Mini App initData, signed with the bot token.

Telegram passes `initData` to the Mini App; the app sends it in the `Authorization: tma <initData>` header.
We check its HMAC (https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app)
and its age, so no login or password is needed and nobody can act as another user.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from aiogram.utils.web_app import safe_parse_webapp_init_data

MAX_AGE = timedelta(days=1)


class AuthError(Exception):
    pass


@dataclass
class TgIdentity:
    id: int
    first_name: str = ""
    username: str = ""
    language_code: str = ""
    start_param: str = ""


def parse_init_data(bot_token: str, init_data: str, now: datetime) -> TgIdentity:
    try:
        data = safe_parse_webapp_init_data(bot_token, init_data)
    except ValueError as exc:
        raise AuthError("bad initData signature") from exc
    if data.user is None:
        raise AuthError("initData has no user")
    auth_date = data.auth_date if data.auth_date.tzinfo else data.auth_date.replace(tzinfo=timezone.utc)
    if now - auth_date > MAX_AGE:
        raise AuthError("initData expired, reopen the app")
    return TgIdentity(
        id=data.user.id,
        first_name=data.user.first_name or "",
        username=data.user.username or "",
        language_code=data.user.language_code or "",
        start_param=data.start_param or "",
    )
