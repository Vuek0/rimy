"""Shareable achievement cards: "7 days in a row", "50 words": a picture in Rimy's style with the sloth.

Rendered with Pillow on the server (JPEG), in the learner's base language. Two formats:
"post" 1080x1350 for chats, "story" 1080x1920 for Telegram stories.
The font is Inter (Debian's fonts-inter, installed in the Docker image, the same font as the promo video);
without it (tests, a dev machine) Pillow's built-in font is used.
"""

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from bot.langs import get_lang

ASSETS = Path(__file__).parent / "assets"
FONT_DIR = Path("/usr/share/fonts/opentype/inter")
SIZES = {"post": (1080, 1350), "story": (1080, 1920)}

# brand palette
DUST, SAGE, FERN, HUNTER, PINE = "#dad7cd", "#a3b18a", "#588157", "#3a5a40", "#344e41"
PAPER = "#f3f2ec"

STREAK_MILESTONES = (3, 7, 14, 30, 50, 100, 150, 200, 365, 500, 1000)
WORD_MILESTONES = (5, 10, 25, 50, 100, 200, 300, 500, 750, 1000, 1500, 2000)


def ru_plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _label(kind: str, n: int, lang: str) -> str:
    if lang == "uz":
        return "kun ketma-ket" if kind == "streak" else "ta so'z yodlandi"
    if lang == "en":
        if kind == "streak":
            return "day in a row" if n == 1 else "days in a row"
        return "word learned" if n == 1 else "words learned"
    if kind == "streak":
        return ru_plural(n, "день", "дня", "дней") + " подряд"
    return ru_plural(n, "слово", "слова", "слов") + " в копилке"


def _subtitle(kind: str, target: str, lang: str) -> str:
    name = get_lang(target).name(lang)
    if lang == "uz":
        return f"Rimy bilan {name} tilini o'rganyapman"
    if lang == "en":
        return f"Learning {name} with Rimy"
    return f"Учу {name} с Rimy"


def _badge(kind: str, lang: str) -> str:
    """A small line above the number: what this achievement is."""
    if kind == "streak":
        return {"uz": "DANGASA SERIYA", "en": "LAZY STREAK"}.get(lang, "ЛЕНИВЫЙ СТРИК")
    return {"uz": "SO'Z BOYLIGI", "en": "VOCABULARY"}.get(lang, "СЛОВАРНЫЙ ЗАПАС")


CTA = {"ru": "Учи слова голосом", "uz": "So'zlarni ovoz bilan o'rgan", "en": "Learn words by voice"}


def milestone_reached(kind: str, before: int, after: int) -> int | None:
    """The milestone crossed when a value went from `before` to `after`, if any."""
    steps = STREAK_MILESTONES if kind == "streak" else WORD_MILESTONES
    crossed = [m for m in steps if before < m <= after]
    return crossed[-1] if crossed else None


@dataclass(frozen=True)
class CardSpec:
    kind: str  # streak / words
    n: int
    lang: str  # base language of the texts
    target: str  # the language being learned
    fmt: str = "post"  # post / story


@lru_cache(maxsize=32)
def _font(name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = FONT_DIR / name
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


@lru_cache(maxsize=4)
def _sloth(size: int) -> Image.Image:
    """The mascot avatar, cut to a circle (the source has black corners)."""
    src = Image.open(ASSETS / "sloth.png").convert("RGB").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((6, 6, size * 4 - 6, size * 4 - 6), fill=255)
    out = Image.new("RGBA", (size, size))
    out.paste(src, (0, 0), mask.resize((size, size), Image.LANCZOS))
    return out


def _center(draw: ImageDraw.ImageDraw, y: int, text: str, font, fill: str, width: int) -> int:
    """Draw text centred horizontally with its top at y; returns the bottom."""
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (right - left)) / 2 - left, y - top), text, font=font, fill=fill)
    return y + (bottom - top)


def _fit(draw: ImageDraw.ImageDraw, text: str, name: str, size: int, max_width: int):
    """The largest font size (down from `size`) at which the text fits the width."""
    while size > 20:
        font = _font(name, size)
        left, _, right, _ = draw.textbbox((0, 0), text, font=font)
        if right - left <= max_width:
            return font
        size -= 4
    return _font(name, size)


def render(spec: CardSpec) -> bytes:
    width, height = SIZES.get(spec.fmt, SIZES["post"])
    img = Image.new("RGB", (width, height), PAPER)

    # soft background: paper → dust, with two blurred sage blobs
    shade = Image.linear_gradient("L").resize((width, height))
    img = Image.composite(Image.new("RGB", (width, height), DUST), img, shade)
    blobs = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blobs)
    bd.ellipse((-260, -200, 520, 520), fill=(163, 177, 138, 110))
    bd.ellipse((width - 420, height - 700, width + 300, height - 40), fill=(88, 129, 87, 70))
    img.paste(blobs.filter(ImageFilter.GaussianBlur(120)), (0, 0), blobs.filter(ImageFilter.GaussianBlur(120)))
    draw = ImageDraw.Draw(img)

    pad = 72
    # top: wordmark and the language pill
    draw.text((pad, pad - 8), "rimy", font=_font("InterDisplay-ExtraBold.otf", 72), fill=PINE)
    lang = get_lang(spec.target)
    pill_font = _font("Inter-Bold.otf", 30)
    pill_text = lang.name(spec.lang).upper()
    l, t, r, b = draw.textbbox((0, 0), pill_text, font=pill_font)
    pw, ph = r - l + 56, 64
    px, py = width - pad - pw, pad
    draw.rounded_rectangle((px, py, px + pw, py + ph), radius=32, fill=(163, 177, 138))
    draw.text((px + 28 - l, py + (ph - (b - t)) / 2 - t), pill_text, font=pill_font, fill=PINE)

    # the content block, centred vertically between the header and the footer
    sloth_size = 400 if spec.fmt == "post" else 480
    number = str(spec.n)
    num_font = _fit(draw, number, "InterDisplay-Black.otf", 300 if spec.fmt == "post" else 360, width - 2 * pad)
    _, nt, _, nb = draw.textbbox((0, 0), number, font=num_font)
    block = sloth_size + 56 + 34 + 28 + (nb - nt) + 24 + 70 + 30 + 46
    y = max(190, (height - 180 - block) // 2 + 40)

    sloth = _sloth(sloth_size)
    ring = 14
    draw.ellipse(
        ((width - sloth_size) // 2 - ring, y - ring, (width + sloth_size) // 2 + ring, y + sloth_size + ring),
        fill=PAPER,
    )
    img.paste(sloth, ((width - sloth_size) // 2, y), sloth)
    y += sloth_size + 56

    y = _center(draw, y, _badge(spec.kind, spec.lang), _font("Inter-Bold.otf", 34), FERN, width) + 28
    y = _center(draw, y, number, num_font, HUNTER, width) + 24
    y = _center(draw, y, _label(spec.kind, spec.n, spec.lang), _fit(draw, _label(spec.kind, spec.n, spec.lang), "Inter-Bold.otf", 70, width - 2 * pad), PINE, width) + 30
    sub = _subtitle(spec.kind, spec.target, spec.lang)
    _center(draw, y, sub, _fit(draw, sub, "Inter-Medium.otf", 46, width - 2 * pad), FERN, width)

    # footer: a pine bar with the call to action and the bot's handle
    fh = 120
    fy = height - pad - fh
    draw.rounded_rectangle((pad, fy, width - pad, fy + fh), radius=36, fill=PINE)
    cta_font = _font("Inter-Bold.otf", 40)
    handle_font = _font("Inter-Medium.otf", 36)
    cta, handle = CTA.get(spec.lang, CTA["ru"]), "@rimy_ai_bot"
    l, t, r, b = draw.textbbox((0, 0), cta, font=cta_font)
    draw.text((pad + 44 - l, fy + (fh - (b - t)) / 2 - t), cta, font=cta_font, fill=PAPER)
    l, t, r, b = draw.textbbox((0, 0), handle, font=handle_font)
    draw.text((width - pad - 44 - (r - l) - l, fy + (fh - (b - t)) / 2 - t), handle, font=handle_font, fill=SAGE)

    out = BytesIO()
    img.save(out, "JPEG", quality=90, optimize=True)
    return out.getvalue()


# --- the message that carries the card ---

CAPTIONS = {
    "ru": {
        "streak": "🔥 <b>{n} {unit} подряд!</b> Ленивый стрик держится 🦥\nПерешли карточку друзьям: пусть тоже попробуют.",
        "words": "🎉 <b>{n} {unit} в копилке!</b> Медленно, но верно 🦥\nПерешли карточку друзьям: пусть тоже попробуют.",
    },
    "uz": {
        "streak": "🔥 <b>{n} kun ketma-ket!</b> Dangasa seriya davom etmoqda 🦥\nKartani do'stlaringga yubor: ular ham sinab ko'rsin.",
        "words": "🎉 <b>{n} ta so'z!</b> Sekin, lekin ishonchli 🦥\nKartani do'stlaringga yubor: ular ham sinab ko'rsin.",
    },
    "en": {
        "streak": "🔥 <b>{n} {unit} in a row!</b> The lazy streak goes on 🦥\nSend the card to friends so they can try too.",
        "words": "🎉 <b>{n} {unit} learned!</b> Slowly but surely 🦥\nSend the card to friends so they can try too.",
    },
}
SHARE_TEXT = {
    "ru": "Учу слова голосом с Rimy 🦥 Попробуй тоже:",
    "uz": "Rimy bilan so'zlarni ovoz bilan o'rganyapman 🦥 Sen ham sinab ko'r:",
    "en": "I'm learning words by voice with Rimy 🦥 Try it too:",
}
SHARE_BUTTON = {"ru": "📤 Поделиться с другом", "uz": "📤 Do'stga ulashish", "en": "📤 Share with a friend"}
STORY_BUTTON = {"ru": "Поделиться", "uz": "Ulashish", "en": "Share"}


def caption(kind: str, n: int, lang: str) -> str:
    if lang == "en":
        unit = ("day" if n == 1 else "days") if kind == "streak" else ("word" if n == 1 else "words")
    else:
        unit = ru_plural(n, "день", "дня", "дней") if kind == "streak" else ru_plural(n, "слово", "слова", "слов")
    return CAPTIONS.get(lang, CAPTIONS["ru"])[kind].format(n=n, unit=unit)
