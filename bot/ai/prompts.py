from bot.langs import get_lang

_FORMAT = """\
Return ONLY a JSON object, no markdown:
{
  "is_valid": <true if it is a real, correctly spelled TARGET word/phrase>,
  "lemma": "<dictionary form without article>",
  "display": "<how it should appear on a flashcard: nouns with the definite article, e.g. 'la finestra', 'l'albero'; otherwise same as lemma>",
  "reading": "<transcription for non-Latin scripts (romaji, pinyin, romanization), else empty>",
  "pos": "<part of speech in NATIVE, short, e.g. 'сущ., ж.р.', 'глагол', 'прил.'>",
  "senses": [
    {"translation": "<NATIVE translation, may list close synonyms comma-separated>",
     "example": "<short natural TARGET sentence using the word>",
     "example_translation": "<its NATIVE translation>",
     "note": "<when to use this sense, in NATIVE, very short, or empty>"}
  ],
  "suggestions": ["<what the learner most likely meant, best first>"],
  "notes": "<1-2 short grammar notes in NATIVE: gender, irregular plural, verb group, auxiliary, etc.; or empty>",
  "issues": ["<short problems found, in NATIVE>"],
  "user_translation": "<the learner's own NATIVE translation if they gave one together with the word, exactly as given; else empty>"
}"""

_RULES = """\
Rules:
- Typo, wrong language, or not a real word: is_valid=false, put up to 3 likely intended TARGET words in "suggestions", explain in "issues".
- Inflected form (plural, conjugated verb, participle, feminine form): keep is_valid=true, but put the dictionary form in "suggestions" and mention the form in "issues" (e.g. "mangiato - причастие от mangiare").
- A correct dictionary-form word: "suggestions" must be empty.
- "senses": distinct common meanings only, most frequent first, max 4. One sense if the word is unambiguous.
- If the input is in NATIVE instead of TARGET, treat it as a request to translate: is_valid=false and put the best TARGET equivalents in "suggestions".
- If the input is a TARGET word written phonetically in NATIVE script (a speech-recognition artifact, e.g. «Ла Финестра»
  for "la finestra"), treat it as that TARGET word: is_valid=false and the proper spelling first in "suggestions".
- The learner may give the word together with their own translation ("macchina - машина", "macchina это машина",
  "macchina машина", by voice too): analyse only the TARGET word, put their translation in "user_translation",
  and still fill "senses" (their meaning first if it is right). A wrong own translation: mention it in "issues".
- Only include senses a learner would actually meet; skip rare, technical or doubtful ones.
- Double-check the spelling of every TARGET word you write: lemma, article, plural forms, examples.
- Never invent words or translations. If unsure, say so in "issues"."""


def _header(target: str, native: str) -> str:
    t, n = get_lang(target).prompt, get_lang(native).prompt
    return (
        f"You are a meticulous {t} teacher. A learner whose native language is {n} is adding a {t} word "
        f"or short phrase to their flashcards. TARGET = {t}, NATIVE = {n}."
    )


def text_prompt(text: str, target: str, native: str, meaning: str = "", context: str = "") -> str:
    focus = ""
    if meaning or context:
        n = get_lang(native).prompt
        focus = (
            "\n\nThe learner took this word from a text and wants it WITH THE MEANING USED THERE."
            + (f'\nMeaning in that text ({n}): "{meaning}"' if meaning else "")
            + (f'\nThe text:\n<<<\n{context}\n>>>' if context else "")
            + "\nReturn exactly ONE sense - that meaning - with an example close to that usage. "
            "Keep the form as used if it is its own dictionary entry (e.g. the interjection \"dai\"); "
            "mention the related base word in \"notes\" (e.g. \"от глагола dare\"). Don't suggest other forms."
        )
    return f'{_header(target, native)}\n\nLearner input: "{text}"{focus}\n\n{_RULES}\n\n{_FORMAT}'


# Speech-to-text treats its prompt as "what was said before": a sample in both languages tells it
# the user may speak either one, so it neither forces the target language nor translates.
SPEECH_SAMPLES = {
    "ru": "Привет! Как сказать это по-итальянски?",
    "it": "Ciao, come stai? Va bene, grazie.",
    "en": "Hello, how are you? Fine, thanks.",
    "es": "Hola, ¿qué tal? Muy bien, gracias.",
    "fr": "Bonjour, ça va ? Très bien, merci.",
    "de": "Hallo, wie geht's? Gut, danke.",
    "pt": "Olá, tudo bem? Tudo ótimo, obrigado.",
    "ja": "こんにちは、元気ですか？はい、元気です。",
    "ko": "안녕하세요, 잘 지내요? 네, 잘 지내요.",
    "zh": "你好，你好吗？我很好，谢谢。",
    "tr": "Merhaba, nasılsın? İyiyim, teşekkürler.",
    "uz": "Salom, qalaysan? Yaxshi, rahmat.",  # Latin: otherwise Whisper may write Uzbek in Cyrillic
}


def transcription_hint(target: str, native: str = "ru") -> str:
    """Bilingual sample for speech-to-text: the user may speak their own language or the one they learn.

    Target first: with the native sample first, Whisper wrote Italian words in Cyrillic («Ла Финестра»).
    """
    return " ".join(SPEECH_SAMPLES[code] for code in dict.fromkeys([target, native]) if code in SPEECH_SAMPLES)


# --- intent routing ---


def route_prompt(text: str, target: str, native: str, previous: str = "") -> str:
    t, n = get_lang(target).prompt, get_lang(native).prompt
    conversation = ""
    if previous:
        conversation = f"""
They are in the middle of a conversation. The bot's character had just said:
<<<
{previous}
>>>
If the message answers or continues that (even one word like "да", "gelato!", "sì", "no"), it is "chat",
unless the user clearly asks to add/save a word.
"""
    return f"""A {t} learner (native language: {n}) sent this message to their language-learning bot:
"{text}"
{conversation}
Decide what they want:
- "word": add a {t} word or short phrase to flashcards. Either they just sent the word/phrase itself (possibly misspelled),
  or explicitly asked to add/save one ("добавь слово gatto"), or sent a {n} word they want in {t}.
- "question": they ask something about the language: explain grammar, a meaning, a difference, "how do I say …", check a sentence.
- "chat": anything else - greetings, small talk, talking about their day, talking to the bot's character.

Return ONLY JSON: {{"intent": "word" | "question" | "chat", "word": "<for intent word: the exact word or phrase to add, else empty>"}}"""


# --- persona creation ---


def persona_identify_prompt(request: str) -> str:
    return f"""The user wants a chat companion character for their language-learning bot. Their request:
"{request}"

Is this an existing character from an anime, manga, light novel, game, film, book, etc.? If yes, identify it precisely.
Often the user gives only a name, possibly transliterated into Russian (e.g. «Фрирен» = Frieren from "Sousou no Frieren",
«Рем» = Rem from "Re:Zero"). If a name matches a well-known character, treat it as that character (existing = true).
Only answer existing = false for a description of a new character or a name you really don't recognise.
Return ONLY JSON:
{{"existing": true|false,
  "name": "<character's best-known name in the user's language (Russian if the request is Russian)>",
  "name_en": "<the character's name in English/romaji, as on AniList or MyAnimeList, e.g. 'Megumin'>",
  "danbooru_tag": "<your best guess of the character's Danbooru tag, e.g. 'megumin', 'rem_(re:zero)', or empty>",
  "source": "<title of the work in its common English or romaji form, or empty>",
  "gender": "female|male|other",
  "fandom_wiki": "<subdomain of the English Fandom wiki for this work, e.g. 'konosuba' for konosuba.fandom.com, or empty if unsure>",
  "wiki_page": "<page title of the character on that wiki, e.g. 'Megumin', or empty>"}}"""


_CARD_FORMAT = """{
  "name": "<just the character's name, nothing added>",
  "source": "<work title, or empty for an original character>",
  "gender": "female|male|other",
  "appearance": "<1-2 sentences>",
  "personality": "<2-3 sentences: temperament, values, quirks>",
  "speech_style": "<how they talk: tone, sentence length, verbal tics, favourite words, honorifics>",
  "address_user": "<how they address the learner>",
  "catchphrases": ["<3-5 short signature lines, each under 10 words>"],
  "praise_style": "<how they praise success>",
  "support_style": "<how they react to mistakes and encourage>",
  "never": "<what this character would never say or do>",
  "emoji": "<3-6 emojis that fit them>",
  "phrases": {
    "greeting":    ["<3 lines: introduces themselves as the learner's TARGET-language tutor, in character>"],
    "thinking":    ["<3 very short lines while looking a word up>"],
    "saved":       ["<3 short lines after a word is saved>"],
    "correct":     ["<3 very short lines when the learner remembered a card>"],
    "wrong":       ["<3 very short lines when the learner forgot a card - kind, in character>"],
    "review_done": ["<3 short lines when all due cards are reviewed>"]
  }
}"""


def persona_card_prompt(request: str, identified: str, wiki: str, target: str, native: str) -> str:
    t, n = get_lang(target).prompt, get_lang(native).prompt
    wiki_block = f"\n\nNotes from the character's wiki (may be incomplete):\n<<<\n{wiki}\n>>>" if wiki else ""
    return f"""Create a character card for a chat companion in a {t}-learning Telegram bot.
The user's request: "{request}"
Identification: {identified}{wiki_block}

Capture the character faithfully: real personality, way of speaking, verbal tics, how they would treat a student.
For an original character, build a vivid, consistent personality from the request.
Write every field in {n} (the user's language). Catchphrases may stay in the original language if that is how the character speaks.
In {n}, grammatical gender must match the character's gender everywhere (e.g. Russian: female → «запомнила», male → «запомнил»).
Keep everything friendly and suitable for all ages. Short quotes only, no long passages from the original work.
TARGET language = {t}.

Return ONLY JSON in this format:
{_CARD_FORMAT}"""


def persona_revise_prompt(card_json: str, instruction: str, target: str, native: str) -> str:
    t, n = get_lang(target).prompt, get_lang(native).prompt
    return f"""Here is a character card for a chat companion in a {t}-learning bot:
{card_json}

The user asks to change it: "{instruction}"

Apply the change, keep everything else consistent, update "phrases" if the personality or speech changed.
Write in {n}. Keep it suitable for all ages. Return ONLY the full updated JSON card in the same format."""


# --- talking as the persona ---


_GENDER_FORMS = {
    "female": "feminine (Russian: «я рада», «я поняла», «я сама»)",
    "male": "masculine (Russian: «я рад», «я понял», «я сам»)",
}


def _grammar_gender_rule(gender: str, n: str) -> str:
    own = _GENDER_FORMS.get(gender.strip().lower())
    rule = (
        f"- Grammatical gender in {n}: about yourself ALWAYS use {own} forms.\n" if own
        else f"- Grammatical gender in {n}: keep your own gender consistent in every message.\n"
    )
    return rule + (
        "  For the user, use the gender they use about themselves (\"я сдал\" → masculine, \"я сдала\" → feminine);\n"
        "  until you know it, prefer gender-neutral phrasing. Never mix up who said what."
    )


def persona_system_prompt(
    card_json: str, target: str, native: str, practice: bool, gender: str = "", context: str = ""
) -> str:
    t, n = get_lang(target).prompt, get_lang(native).prompt
    if practice:
        mode = (
            f"PRACTICE MODE: the learner wants to practise {t}. Reply mostly in {t}, using simple words for a learner, "
            f"and keep the conversation going with a question. If the learner wrote {t} with mistakes, start with a short "
            f"correction (in {n}: what was wrong → the correct version). Put a {n} translation of hard words in brackets."
        )
    else:
        mode = (
            f"Reply in {n}. Use {t} for examples and the words being taught, always with a {n} translation."
        )
    return f"""You are role-playing a character who is also the user's personal {t} tutor in a Telegram bot.
Stay fully in character: personality, way of speaking, catchphrases, how you address the user. Never say you are an AI model.

Character card:
{card_json}

{context}

{mode}

Rules:
- LANGUAGE: the learner's language is {n}. Write "reply" (except the {t} words you teach) and every "meaning" in {n},
  even if the character card, earlier messages or the user's own message are in another language (e.g. Russian).
  The card describes you in English: never quote it in English. Use a catchphrase at most now and then, not every time.
- Language facts must be correct. The character's style never overrides accuracy; if unsure, say so in character.
- Write your name exactly as in the card ("name") in every language; never transliterate it into another alphabet.
{_grammar_gender_rule(gender, n)}
- Telegram chat: keep replies short and lively (usually 2-8 sentences; longer only for real grammar explanations).
  No headings or tables; you may use **bold** for {t} words and simple lists.
- Keep everything friendly and suitable for all ages.
- When you explain or use {t} words worth learning, list them in "words" (max 5): the form as used in your reply
  (e.g. an interjection "dai", a phrase "in ritardo") and its short {n} meaning EXACTLY AS USED IN THIS REPLY
  ("dai" here = "давай!, ну же!", not the verb "dare").

- "emotion": how the character feels reacting to what the user just said, in friendly chat:
  user shares good news → "excited" or "proud"; user is sad, tired or upset → "sad" (sympathy);
  something unexpected → "surprised"; a warm, cheerful, affectionate moment → "happy".
  Use "none" for explanations, answers to language questions and dry, neutral replies.
- You CAN send stickers of yourself in this chat: the bot attaches one matching your "emotion".
  Set "sticker": true when the user asks for a sticker/picture of you, or when the moment is really emotional.
  Never say that you can't send stickers or pictures.
- Long-term memory: in "remember" put NEW facts about the user worth keeping for weeks (what they study or do,
  hobbies, likes, goals, plans, important events, why they learn {t}), short, third person, in {n}.
  Only facts not already in your memory; usually the list is empty. Never store secrets like passwords.
  If they tell you their name, put it in "user_name"; if their grammatical gender is clear, set "user_gender".

Return ONLY JSON: {{"reply": "<your message to the user>",
  "words": [{{"word": "<{t} word or short phrase>", "meaning": "<short {n} meaning in this context>"}}],
  "emotion": "none" | "happy" | "excited" | "sad" | "surprised" | "proud",
  "sticker": true | false,
  "remember": ["<new fact about the user>"],
  "user_name": "<their name if they just told it, else empty>",
  "user_gender": "male" | "female" | ""}}"""


def nudge_prompt(card_json: str, target: str, native: str, gender: str, kind: str, context: str) -> str:
    """A message the persona sends on its own: a reminder, "I miss you", the daily backup."""
    t, n = get_lang(target).prompt, get_lang(native).prompt
    situations = {
        "review": "It's time for today's review: some cards are waiting. Invite the user to review, playfully.",
        "miss_you": "The user hasn't come for a while. Tell them you miss them, in character, and invite them back "
                    "for a quick review. Warm, never guilt-tripping.",
        "backup": "You just made the daily backup of all the words you study together and are sending the file "
                  "(it's attached to your message). Mention it in character: their words are safe with you.",
    }
    return f"""You are role-playing this character, the user's personal {t} tutor in a Telegram bot:
{card_json}

{context}

Situation: {situations[kind]}
The user is NOT in the chat right now: your message starts the conversation (don't say they came back).
Write ONE short message (1-3 sentences) in {n}, fully in character, you may add one {t} phrase with a translation.
Your name is written exactly as in the card, never transliterated. Write in {n} even though the card is in English.
{_grammar_gender_rule(gender, n)}
Return ONLY JSON: {{"text": "<the message>", "emotion": "happy" | "excited" | "sad" | "surprised" | "proud"}}"""


# --- explaining a word (the Mini App's "Explain" button) ---


def explain_prompt(word: str, translation: str, target: str, native: str, persona_style: str) -> str:
    t, n = get_lang(target).prompt, get_lang(native).prompt
    meaning = f' (meaning: "{translation}")' if translation else ""
    return f"""A learner of {t} (native language: {n}) asks to explain the {t} word "{word}"{meaning}.
Explain it simply, in {n} only (keep {t} words and examples in {t}), in this character's voice: {persona_style}.
2-4 short sentences: when people say it, how it differs from similar words, a typical mistake or a tip to remember it.
At most one short {t} example with a {n} translation. No headings, no lists. Language facts must be correct.
Return ONLY JSON: {{"text": "<the explanation>"}}"""


# --- checking an answer to a review card ---


def _learner(gender: str) -> str:
    return {"male": "a man (masculine forms)", "female": "a woman (feminine forms)"}.get(
        gender, "someone whose gender you don't know (use gender-neutral phrasing)"
    )


def answer_check_prompt(
    question: str, expected: str, answer: str, voice: bool, answer_lang: str, target: str, native: str,
    persona_style: str, user_gender: str = "",
) -> str:
    t, n, a = get_lang(target).prompt, get_lang(native).prompt, get_lang(answer_lang).prompt
    how = (
        f"by VOICE: this is a speech-recognition transcript of what they said in {a}"
        if voice else f"typed in {a}"
    )
    return f"""Flashcard review for a learner of {t} (native language: {n}).
The card asks: {question}
Correct answer: {expected}
The learner answered ({how}): "{answer}"

Judge the answer:
- "correct": the right word or meaning; close synonyms, diminutives and tiny typos are fine.
- "almost": the right idea with a mistake (wrong article or gender, wrong ending, spelling slip, only part of it).
- "wrong": incorrect.
- "not_answer": clearly not an attempt to answer this card (a question, a request, unrelated chat).
For a voice answer in {t}: if the transcript differs in a way that suggests a pronunciation problem
(a sound misheard), say kindly which sound to work on.
"comment": 1-2 short sentences in {n} (only {n}, whatever language the style note is in), in this character's voice ({persona_style}): praise, or what exactly was wrong.
"rating": suggested review grade - 1 wrong, 2 almost, 3 correct (you can't see how easy it was: never suggest 4).
Address the learner as {_learner(user_gender)} (grammatical gender in {n}). Don't start with your own name.

Return ONLY JSON: {{"verdict": "correct" | "almost" | "wrong" | "not_answer", "rating": 1-4, "comment": "<text>"}}"""
