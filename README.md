# lang-lrn-bot

A Telegram bot + Mini App for learning foreign words: send a word by text or voice, the AI builds the
flashcard, and spaced repetition (FSRS, as in Anki) makes it stick. A mascot tutor reminds you in Telegram.

## Product (hackathon version)

- **Multi-user.** Anyone can use the bot; `/backup` and `/admin` are for `ADMIN_IDS` only.
- **Telegram Mini App** (`webapp/`, React + Vite + TypeScript): add words by text or **voice** (mic button),
  review cards (answer by text or voice, AI checks it), word list with pronunciation, stats, language switch.
  It talks to a FastAPI backend (`bot/api/`) that runs in the same process as the bot. Every request is
  authenticated with Telegram's signed `initData` — no logins.
- **Freemium.** Free plan: a few AI actions a day (`FREE_*_PER_DAY`); reviewing cards is always free.
  **Premium** is a 30-day Telegram Stars subscription (`/premium` in the chat, or the paywall in the app).
- **Analytics.** Funnel events (`start → first_word → first_review → app_open → limit_reached →
  paywall_view → purchase`) are stored in the `events` table. Deep links `t.me/<bot>?start=ref_<code>`
  record where a user came from. `/admin [days]` shows users, the funnel, leads per ref code and Stars earned.
- **Mascot.** The tutor is the app's mascot for everyone (`bot/persona/card.py`, `MASCOT_NAME`).

### Mini App: development

```bash
cd webapp && npm install && npm run dev   # Vite on :5173, proxies /api to the bot on :8080
npm run build                              # webapp/dist, served by the bot's API at /
```

In @BotFather set the Mini App URL to `WEBAPP_URL` (HTTPS). Locally you can expose :8080 with any HTTPS tunnel.

The bot's interface is in Russian; the language you learn is configurable (Italian by default, plus English, Spanish, French, German, Portuguese, Japanese, Korean, Chinese, Turkish).

## Features

- **Add words by text or voice.** The AI (Groq / OpenAI / Gemini) translates the word, checks spelling and the dictionary form, asks which meaning you want, and shows a card preview before saving.
- **Anki-style review.** Spaced repetition with FSRS, cards in both directions (IT→RU and RU→IT), grades Again / Hard / Good / Easy.
- **Answer cards by text or voice.** The AI checks your answer, allowing synonyms and small typos. For spoken answers it tells you which sound to work on. The persona comments on the answer and the suggested grade is marked 👉, but you always pick the grade yourself.
- **Pronunciation** 🔊. A native neural voice reads the word and its example (Microsoft Edge TTS, free). The voice matches the persona's gender, and each phrase is synthesized once and then cached.
- **Several languages**, each with its own deck (`/lang`).
- **Persona tutor** (`/persona`). The bot talks as any character: someone from an anime, manga or game (details come from AniList, plus Fandom when it's reachable), or an original character described in your own words. You can edit the character card in plain language. The default persona is Roxy.
- **Character art.**
  - Pick an avatar from real artwork on Danbooru (Safebooru as a fallback) or upload your own.
  - Only general-rated art is used, and anything tagged as AI-generated is filtered out.
- **Sticker reactions.** The persona sometimes reacts with an emotion sticker:
  - **reviewing cards** — sad after a mistake, happy after a right answer, always at the end of a session;
  - **small talk** — sometimes, when the AI sees a strong emotion (you passed an exam, you feel down);
  - **saving words** — only for milestones: 25/50/100/… words in the deck, 10 words in a day, coming back after a break;
  - **answers to questions and explanations** — never.

  Stickers are made from solo arts: a square crop from the top of the art (where the face usually is), 512 px, WebP. Set `REACTION_STYLE=photo` to get full pictures instead. Sent pictures are cached by their Telegram `file_id`.
- **Your own sticker sets** (`/stickers`).
  - For every emotion the bot shows candidates as real stickers: "➕" adds one to your set, "👎" removes it for good.
  - Once a set exists, reactions come only from it.
  - You can forward **any Telegram sticker** to the bot and bind it to an emotion, so even personas without artwork can have stickers.
- **Memory and mood.**
  - The persona remembers your name and facts about you from conversations. `/memory` shows what it remembers and lets you wipe it.
  - It knows your progress and the words you keep forgetting.
  - Its mood depends on your streak and on how long you've been away.
  - The conversation history is stored in the database and survives restarts.
- **Reminders** (`/remind`, 12:00 and 20:00 by default). The persona invites you to review due cards and, if you've been away for a while, tells you it misses you, with a sticker. It doesn't bother you if you've just been active.
- **Daily backup.** At 3:00 the persona sends the database file (`.db.gz`) with a sticker and a note. `/backup` sends it right away.
- **Questions and small talk.** Ask things like "explain the congiuntivo" or "how do I say 'I'm late'?". The bot works out whether you sent a word or a question and answers in the persona's style, with "➕" buttons to add the words it used. `/practice` switches to conversation practice in the target language, with corrections.
- **Main menu** under the input field, plus `/list`, `/stats` (including your streak) and `/delete`.

**Stack:** Python 3.12, aiogram 3, SQLAlchemy 2 + SQLite, Alembic, openai (for Groq/OpenAI), google-genai, fsrs, edge-tts, Pillow, Docker.

## Running locally

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt -r requirements-dev.txt   # Linux/macOS: .venv/bin/pip
cp .env.example .env    # then fill it in
.venv/Scripts/python -m bot
```

Environment variables:

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | yes | token from @BotFather |
| `OWNER_ID` | yes | your Telegram user ID (ask @userinfobot). The bot answers only this user |
| `GROQ_API_KEY` | at least one AI key | console.groq.com: free and fast, text plus Whisper for voice |
| `OPENAI_API_KEY` | | platform.openai.com (paid) |
| `GEMINI_API_KEY` | | aistudio.google.com (free, but often overloaded) |
| `GROQ_MODELS`, `OPENAI_MODEL`, `GEMINI_MODELS` | no | models to use; in comma-separated lists the next model is tried if the first one fails |
| `DANBOORU_LOGIN`, `DANBOORU_API_KEY` | no | Danbooru account for art search (My Account → API Key). Without it, or when Danbooru blocks the server's IP (data-center IPs often get `403`), art is searched on Safebooru |
| `REACTION_STYLE` | no | `sticker` (default) or `photo` |
| `DATABASE_URL` | no | default `sqlite+aiosqlite:///data/bot.db` |
| `TIMEZONE` | no | default `Asia/Tashkent` |
| `DEFAULT_TARGET_LANG` | no | default `it` |

AI providers form a chain: **Groq → OpenAI → Gemini**. Only providers with a key take part. If one is down, rate-limited, or returns a broken answer, the bot moves on to the next one right away.

Tests: `pytest`.

To create a migration after changing the models:

```bash
alembic revision --autogenerate -m "what changed"
```

## Deployment (push to main → server)

A `git push` to `main` runs GitHub Actions:
1. **Test.** Runs the test suite (pull requests run the tests too).
2. **Build.** Builds the Docker image and publishes it to GHCR (`ghcr.io/<owner>/<repo>:<commit>`).
3. **Deploy.** Asks the server over SSH to update to that commit. On the server, `scripts/deploy.sh` pulls the code, downloads the image and restarts the container. If the new version doesn't come up, it rolls back to the previous one.

### One-time setup

**On the server** (with Docker installed):
```bash
git clone https://github.com/<owner>/<repo>.git ~/lang-lrn-bot
nano ~/lang-lrn-bot/.env          # bot keys, as in .env.example
```
Add a separate deploy key to `~/.ssh/authorized_keys` **with a restriction**, so it can do nothing but trigger a deploy:
```
command="/home/ubuntu/lang-lrn-bot/scripts/deploy.sh",restrict ssh-ed25519 AAAA... github-deploy
```

**On GitHub:**
- Go to Settings → Environments → `production` and limit Deployment branches to `main`. Add these secrets there:

  | Secret | Value |
  |---|---|
  | `VPS_HOST` | server IP |
  | `VPS_USER` | user, e.g. `ubuntu` |
  | `VPS_SSH_KEY` | private part of the deploy key |
  | `VPS_KNOWN_HOSTS` | output of `ssh-keyscan <IP>` |
- After the first build, go to Packages → the image → Package settings → **Change visibility → Public**. The server then pulls the image without any token.

### Restoring from a backup

Every day the bot sends the owner a `lang-lrn-bot-YYYY-MM-DD.db.gz` file. To restore it on the server:
```bash
gunzip lang-lrn-bot-2026-11-20.db.gz
cd ~/lang-lrn-bot && docker compose stop bot
docker run --rm -v lang-lrn-bot_bot-data:/data -v "$PWD":/src alpine \
  sh -c "cp /src/lang-lrn-bot-2026-11-20.db /data/bot.db && chown -R 1000:1000 /data"
docker compose start bot
```

## Security

- **Bot and AI keys** live only in `.env` on the server. They are not in the repository or in GitHub Secrets, and `.env` is in `.gitignore`.
- **The bot answers only its owner** (`OWNER_ID`), so strangers can't use up your API limits.
- **The deploy key** is locked to `scripts/deploy.sh` on the server (`command=…,restrict`): no shell and no port forwarding. The script accepts only `deploy <sha>` and deploys only commits that are on `origin/main`.
- **Deploy secrets** are in the `production` environment, which only the `main` branch can use. Pull requests, including those from forks, only run the tests and never see the secrets.
- **Workflow permissions** are minimal (`contents: read`); only the build step can write to GHCR.
- **Dependabot** proposes weekly updates for dependencies, Actions and the base image.
- **The container** runs as an unprivileged user.

Found a vulnerability? Please contact the repository owner privately instead of opening a public issue.

## License

[MIT](LICENSE)
