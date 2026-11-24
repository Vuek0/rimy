"""Character info for building a persona card.

- AniList (public GraphQL API, no key): character descriptions for anime/manga/light novels. Main source.
- Fandom wikis (MediaWiki API): Personality / Appearance sections. Often hidden behind a Cloudflare
  challenge for bots, so it's only a bonus when it happens to work.
"""

import logging
import re

import aiohttp

log = logging.getLogger(__name__)

USER_AGENT = "lang-lrn-bot/0.1 (personal Telegram bot for language learning)"
TIMEOUT = aiohttp.ClientTimeout(total=12)
WANTED_SECTIONS = re.compile(r"personality|appearance|character|personnalit|личность|характер|внешност", re.I)
MAX_SECTION_CHARS = 2500
MAX_TOTAL_CHARS = 6000


def clean_wikitext(text: str) -> str:
    text = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    for _ in range(5):  # templates can be nested: strip innermost first
        text, n = re.subn(r"\{\{[^{}]*\}\}", "", text)
        if not n:
            break
    text = re.sub(r"\[\[(?:File|Image|Файл|Category|Категория):[^\]]*\]\]", "", text, flags=re.I)
    text = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[https?://\S+\s([^\]]*)\]", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"'{2,}", "", text)
    text = re.sub(r"^=+\s*(.*?)\s*=+$", r"\1:", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def api_url(wiki: str, lang: str = "") -> str | None:
    """'konosuba' → https://konosuba.fandom.com/api.php; with lang 'ru' → …/ru/api.php"""
    wiki = wiki.strip().lower().removeprefix("https://").removesuffix("/").removesuffix(".fandom.com")
    lang = lang.strip().lower()
    if not re.fullmatch(r"[a-z0-9-]{2,60}", wiki) or (lang and not re.fullmatch(r"[a-z]{2}(-[a-z]{2,4})?", lang)):
        return None
    prefix = "" if lang in ("", "en") else f"{lang}/"
    return f"https://{wiki}.fandom.com/{prefix}api.php"


async def fetch_character_info(wiki: str, page: str, lang: str = "") -> str:
    """Return cleaned Personality/Appearance text, or "" if anything fails. Never raises."""
    api = api_url(wiki, lang)
    if not api or not page.strip():
        return ""
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as http:
            title = await _search(http, api, page)
            if not title:
                return ""
            sections = await _get(http, api, action="parse", page=title, prop="sections", redirects=1)
            wanted = [
                s["index"] for s in sections.get("parse", {}).get("sections", []) if WANTED_SECTIONS.search(s.get("line", ""))
            ][:3]
            if not wanted:  # no such sections: take the intro
                wanted = ["0"]
            parts = []
            for index in wanted:
                data = await _get(http, api, action="parse", page=title, prop="wikitext", section=index, redirects=1)
                wikitext = data.get("parse", {}).get("wikitext", {}).get("*", "")
                parts.append(clean_wikitext(wikitext)[:MAX_SECTION_CHARS])
            return f"[{title}]\n" + "\n\n".join(p for p in parts if p)[:MAX_TOTAL_CHARS]
    except Exception as exc:  # network errors, unknown wiki, unexpected JSON
        log.info("Fandom lookup failed for %s / %s: %s", wiki, page, str(exc).split(",")[0][:120])
        return ""


async def _get(http: aiohttp.ClientSession, api: str, **params) -> dict:
    async with http.get(api, params={**params, "format": "json"}) as response:
        response.raise_for_status()
        return await response.json(content_type=None)


async def _search(http: aiohttp.ClientSession, api: str, page: str) -> str:
    data = await _get(http, api, action="query", list="search", srsearch=page, srlimit=1)
    hits = data.get("query", {}).get("search", [])
    return hits[0]["title"] if hits else ""


# --- AniList ---

ANILIST_URL = "https://graphql.anilist.co"
ANILIST_QUERY = """
query ($search: String) {
  Page(perPage: 5) {
    characters(search: $search, sort: [SEARCH_MATCH, FAVOURITES_DESC]) {
      name { full native }
      description(asHtml: false)
      media(perPage: 3, sort: POPULARITY_DESC) { nodes { title { romaji english native } } }
    }
  }
}"""
MAX_ANILIST_CHARS = 3500


def clean_anilist(text: str) -> str:
    text = re.sub(r"~!.*?!~", "", text, flags=re.S)  # spoilers
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [Name](link) → Name
    text = re.sub(r"__(.+?)__|\*\*(.+?)\*\*", lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def pick_character(characters: list[dict], source: str) -> dict | None:
    """Best search hit; prefer one whose series matches the requested source."""
    if not characters:
        return None
    wanted = _norm(source)
    if wanted:
        for character in characters:
            for media in character.get("media", {}).get("nodes", []):
                titles = [_norm(t or "") for t in media.get("title", {}).values()]
                if any(t and (wanted in t or t in wanted) for t in titles):
                    return character
    return characters[0]


async def fetch_anilist(name: str, source: str = "") -> str:
    """Return a cleaned character description, or "" if anything fails. Never raises."""
    if not name.strip():
        return ""
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as http:
            payload = {"query": ANILIST_QUERY, "variables": {"search": name.strip()}}
            async with http.post(ANILIST_URL, json=payload) as response:
                response.raise_for_status()
                data = await response.json()
        character = pick_character(data.get("data", {}).get("Page", {}).get("characters", []), source)
        if not character or not character.get("description"):
            return ""
        title = character["name"].get("full") or name
        return f"[AniList: {title}]\n" + clean_anilist(character["description"])[:MAX_ANILIST_CHARS]
    except Exception as exc:
        log.info("AniList lookup failed for %s: %r", name, exc)
        return ""


async def character_info(name_en: str, source: str, fandom_wiki: str = "", fandom_page: str = "") -> str:
    """Everything we can find about an existing character, from all sources."""
    parts = [await fetch_anilist(name_en, source)]
    if fandom_wiki:
        parts.append(await fetch_character_info(fandom_wiki, fandom_page or name_en))
    return "\n\n".join(p for p in parts if p)
